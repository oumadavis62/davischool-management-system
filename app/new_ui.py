from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from html import escape
import base64
import re
from urllib.parse import quote
from datetime import datetime
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

@router.get("/", response_class=HTMLResponse)
def davischool_login_page(request: Request):
    if request.session.get("email"):
        return RedirectResponse("/app", status_code=303)
    error = "<div class='err'>This school account is suspended. Please contact the DaviSchool administrator.</div>" if request.query_params.get("suspended") else ("<div class='err'>Invalid username or password.</div>" if request.query_params.get("error") else "")
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>DaviSchool Login</title><style>body{{margin:0;background:#f4f7fb;font-family:Arial,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center}}.box{{width:min(430px,92vw);background:white;border:1px solid #e2e8f0;border-radius:18px;padding:32px;box-shadow:0 18px 50px #0f172a14}}.logo{{font-size:25px;font-weight:900;color:#111827;margin-bottom:5px}}.sub{{color:#64748b;margin-bottom:25px}}label{{display:block;font-size:13px;font-weight:800;color:#334155;margin:14px 0 7px}}input{{width:100%;box-sizing:border-box;padding:13px;border:1px solid #dbe2ea;border-radius:10px;font-size:15px}}button{{width:100%;margin-top:20px;padding:14px;border:0;border-radius:10px;background:#111827;color:white;font-weight:900;font-size:15px;cursor:pointer}}.err{{background:#fff1f2;border:1px solid #fda4af;color:#9f1239;padding:11px;border-radius:10px;margin-bottom:14px}}</style></head><body><div class='box'><div class='logo'>🏫 DaviSchool Management System</div><div class='sub'>Secure school management platform</div>{error}<form method='post' action='/login'><label>Email / Username</label><input name='email' type='email' autocomplete='username' required placeholder='Enter your email'><label>Password</label><input name='password' type='password' autocomplete='current-password' required placeholder='Enter password'><button type='submit'>Sign In</button></form></div></body></html>""")

@router.post("/login")
def davischool_login(request: Request, email: str = Form(...), password: str = Form(...)):
    from app.main import verify_password
    con = _db()
    try:
        user = con.execute("SELECT * FROM users WHERE lower(email)=lower(?) LIMIT 1", (email.strip(),)).fetchone()
    finally:
        con.close()
    if not user:
        return RedirectResponse("/?error=1", status_code=303)
    ok, legacy = verify_password(password, user["password"] or "")
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
        canvas.setFillColorRGB(0.35, 0.39, 0.45)
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
        "title": ParagraphStyle("DaviTitle", parent=styles["Title"], fontSize=15, leading=18, alignment=TA_CENTER, spaceAfter=5),
        "subtitle": ParagraphStyle("DaviSubtitle", parent=styles["Normal"], fontSize=8, leading=10, alignment=TA_CENTER, spaceAfter=8),
        "normal": ParagraphStyle("DaviNormal", parent=styles["Normal"], fontSize=8, leading=10),
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
    contacts = []
    if school_row:
        for key in ("email", "phone", "postal_address", "postal_code"):
            if key in school_row.keys() and school_row[key]:
                value = str(school_row[key])
                if key == "postal_address":
                    value = "P.O. Box " + value
                contacts.append(value)
    contact_text = " · ".join(contacts)
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
    if contact_text:
        text.append(Paragraph(escape(contact_text), styles["small"]))
    if subtitle:
        text.append(Paragraph(escape(subtitle), styles["small"]))
    table = Table([[logo_flowable, text]], colWidths=[28*mm, None])
    table.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LINEBELOW",(0,0),(-1,-1),1,colors.HexColor("#111827")), ("BOTTOMPADDING",(0,0),(-1,-1),5)]))
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
        if role == "teacher":
            nav = [
                ("/app","⌂","Overview",None),
                ("/app/academics","📝","Academics","marks.view"),
                            ("/app/report-cards","📄","Report Cards","reports.view"),
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
        if role not in ("school_admin", "teacher") and school_id:
            con = _db()
            try:
                cur = con.cursor()
                nav = [item for item in nav if item[3] is None or _permission_enabled(cur, int(school_id), role, item[3])]
            finally:
                con.close()
    links="".join(f"<a href='{u}' class='nav'><span>{i}</span>{escape(l)}</a>" for u,i,l,_ in nav)
    initials="".join(x[0] for x in (name or "DaviSchool").split()[:2]).upper()
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{escape(title)} · DaviSchool</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,Arial,sans-serif;background:#f5f7fb;color:#172033}}
.app{{display:flex;min-height:100vh}}.side{{width:250px;background:#111827;color:#cbd5e1;padding:18px 12px;position:fixed;inset:0 auto 0 0;overflow:auto}}
.brand{{font-size:20px;font-weight:900;color:white;padding:8px 12px 24px}}.brand small{{display:block;font-size:10px;color:#94a3b8;margin-top:4px;letter-spacing:1px}}
.nav{{display:flex;gap:11px;align-items:center;color:#cbd5e1;text-decoration:none;padding:10px 12px;border-radius:10px;font-size:13px;margin:3px 0}}.nav:hover{{background:#1f2937;color:white}}
.main{{margin-left:250px;flex:1}}.top{{height:68px;background:white;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;justify-content:space-between;padding:0 28px;position:sticky;top:0;z-index:5}}
.avatar{{width:36px;height:36px;border-radius:50%;background:#111827;color:white;display:flex;align-items:center;justify-content:center;font-weight:800}}
.page{{padding:28px;max-width:1500px;margin:auto}}h1{{font-size:25px;margin:0 0 6px}}.muted{{color:#64748b;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin:22px 0}}.card{{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:18px;box-shadow:0 2px 8px #00000005}}.kpi{{font-size:28px;font-weight:900;margin-top:10px}}.label{{font-size:11px;color:#64748b;text-transform:uppercase;font-weight:800}}
.section{{margin-top:18px}}.section h2{{font-size:16px;margin:0 0 12px}}.actions{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.action{{background:white;border:1px solid #e5e7eb;border-radius:14px;padding:15px;text-decoration:none;color:#172033;font-weight:800;font-size:13px}}.action span{{font-size:21px;display:block;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden}}th,td{{padding:12px;border-bottom:1px solid #eef2f7;text-align:left;font-size:12px}}th{{background:#f8fafc;color:#64748b;font-size:10px;text-transform:uppercase}}
@media(max-width:900px){{.side{{width:72px}}.brand{{font-size:0}}.brand:before{{content:'DS';font-size:18px}}.nav{{justify-content:center;font-size:0}}.nav span{{font-size:17px}}.main{{margin-left:72px}}.grid,.actions{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:600px){{.page{{padding:16px}}.grid,.actions{{grid-template-columns:1fr 1fr}}.top{{padding:0 16px}}}}
</style></head><body><div class='app'><aside class='side'><div class='brand'>DaviSchool<small>MANAGEMENT PLATFORM</small></div>{links}<div style='padding:14px 12px;color:#94a3b8;font-size:10px;line-height:1.4'>Selection-based data entry is enabled throughout the school workspace.</div><a href='/logout' class='nav' style='margin-top:18px'>↪ Logout</a></aside>
<main class='main'><header class='top'><div><strong>{escape(title)}</strong><div class='muted'>{escape(role.replace("_"," ").title())}</div></div><div style='display:flex;gap:10px;align-items:center'><span class='muted'>{escape(name)}</span><div class='avatar'>{escape(initials)}</div></div></header>{body}</main></div></body></html>"""
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
    role=str(request.session.get("role",""))
    if role=="school_admin":
        return True
    if role=="teacher":
        return permission in {"marks.view","marks.edit","reports.view","reports.edit"}
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
    terms = cur.execute("SELECT * FROM terms WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    exams = cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    classes = cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
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
    copts="".join("<option value='%s' %s>%s %s</option>"%(c["id"],"selected" if int(c["id"])==cid else "",escape(str(c["name"])),escape(str(c["stream"] or ""))) for c in classes)
    sopts="".join("<option value='%s' %s>%s</option>"%(s["id"],"selected" if int(s["id"])==subid else "",escape(str(s["name"]))) for s in subjects)
    topts="".join("<option %s>%s</option>"%("selected" if x==term else "",x) for x in TERM_OPTIONS)
    yopts="".join("<option value='%s' %s>%s</option>"%(y,"selected" if y==year else "",y) for y in YEAR_OPTIONS)
    actions=[("/app/academics/marks","📝","Marks Entry","Enter and update learner marks"),("/app/academics/marksheets","📋","Class Marksheets","View class marks"),("/app/academics/subject-analysis","📊","Subject Analysis","Analyse subjects"),("/app/academics/student-analysis","👤","Student Analysis","Analyse a learner"),("/app/academics/class-analysis","🏫","Class Analysis","Analyse a class"),("/app/academics/assessments","🧪","SBA / CBA","Continuous assessment"),("/app/academics/grading","🎯","Grade & Points","Set subject grading rules"),("/app/academics/allocations","👩‍🏫","Teacher Allocation","Assign teachers"),("/app/report-cards","📄","Report Cards","Generate reports"),("/app/report-card-settings","📅","Report Card Dates","Set opening & closing dates"),("/app/exams","⚙","Examinations","Manage examinations"),("/app/subjects","📚","Subjects","Manage subjects"),("/app/classes","🏷","Classes & Streams","Manage classes")]
    action_html="".join("<a class='action' href='%s'><span>%s</span>%s<small>%s</small></a>"%x for x in actions)
    body="<div class='page'><h1>Academic Management</h1><div class='muted'>Select options below to work with marks, assessments, analysis and reports.</div><div class='grid'><div class='card'><div class='label'>Subjects</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Exams</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Classes</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Marks Average</div><div class='kpi'>%.1f%%</div></div></div>"%(len(subjects),len(exams),len(classes),float(stat["avg_mark"] or 0))
    body+="<div class='card section'><h2>Academic Selection</h2><form method='get' action='/app/academics' class='academic-select'><select name='year' class='field' onchange='this.form.submit()'><option value=''>All Years</option>"+yopts+"</select><select name='term' class='field' onchange='this.form.submit()'><option value=''>All Terms</option>"+topts+"</select><select name='exam_id' class='field' onchange='this.form.submit()'><option value=''>All Exams</option>"+eopts+"</select><select name='class_id' class='field' onchange='this.form.submit()'><option value=''>All Classes</option>"+copts+"</select><select name='subject_id' class='field' onchange='this.form.submit()'><option value=''>All Subjects</option>"+sopts+"</select></form></div><div class='section'><div class='actions'>"+action_html+"</div></div>"
    body+="<div class='card section'><h2>Selected Academic Results</h2><div class='grid' style='margin:0'><div class='card'><div class='label'>Entries</div><div class='kpi'>%d</div></div><div class='card'><div class='label'>Average</div><div class='kpi'>%.1f%%</div></div><div class='card'><div class='label'>Highest</div><div class='kpi'>%.1f</div></div><div class='card'><div class='label'>Lowest</div><div class='kpi'>%.1f</div></div></div></div></div><style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff;cursor:pointer}.academic-select{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.action small{display:block;color:#64748b;margin-top:5px}@media(max-width:900px){.academic-select{grid-template-columns:1fr 1fr}}</style>"%(int(selected["entries"] or 0),float(selected["avg_mark"] or 0),float(selected["high"] or 0),float(selected["low"] or 0))
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

def _ensure_overall_grading_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS overall_grading_rules(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER,
        min_total REAL,
        max_total REAL,
        grade TEXT
    )""")

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
    if overall_rules is not None:
        for rule in overall_rules:
            try:
                if float(rule["min_total"]) <= float(average_percentage) <= float(rule["max_total"]):
                    return str(rule["grade"])
            except Exception:
                continue
        return _default_grade_points(average_percentage)[0]
    try:
        _ensure_overall_grading_table(cur)
        rule=cur.execute("""SELECT grade FROM overall_grading_rules
            WHERE school_id=? AND ? BETWEEN min_total AND max_total
            ORDER BY min_total DESC,id DESC LIMIT 1""",(school_id,average_percentage)).fetchone()
        return str(rule["grade"]) if rule else _default_grade_points(average_percentage)[0]
    except Exception as exc:
        print("DAVISCHOOL OVERALL GRADING FALLBACK:", repr(exc), flush=True)
        return _default_grade_points(average_percentage)[0]

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
      "<div class='card section'><table><thead><tr><th>Minimum Average %</th><th>Maximum Average %</th><th>Overall Grade</th><th>Action</th></tr></thead><tbody>"+(rows or "<tr><td colspan='4'>No overall grading bands configured.</td></tr>")+"</tbody></table></div>"
      "<div class='card section'><b>Overall grade:</b> Based on average percentage. <b>Position:</b> ranked automatically by total marks, highest total first; equal totals receive the same position.</div>"
      "<style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}.btn,.btnlink{padding:10px 14px;border:1px solid #dbe2ea;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}.btnlink{background:#fff;color:#172033}</style></div>")
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
    if not student_ids or not exam_ids:
        return {}
    sp = ",".join("?" for _ in student_ids)
    ep = ",".join("?" for _ in exam_ids)
    q = "SELECT student_id,subject_id,marks FROM marks WHERE school_id=? AND student_id IN ("+sp+") AND exam_id IN ("+ep+")"
    params = [sid] + list(student_ids) + list(exam_ids)
    if term:
        q += " AND term=?"; params.append(term)
    if year:
        q += " AND year=?"; params.append(year)
    rows = cur.execute(q, params).fetchall()
    buckets = {}
    for r in rows:
        if r["marks"] is None or str(r["marks"]).strip()=="":
            continue
        buckets.setdefault((int(r["student_id"]),int(r["subject_id"])), []).append(float(r["marks"]))
    return {k: sum(v)/len(v) for k,v in buckets.items() if v}

MARKSHEET_SUBJECT_ORDER = (
    "English", "Kiswahili", "Mathematics", "Integrated Science", "Agriculture",
    "Creative Arts and Sports", "Social Studies", "CRE", "Pre-technical Studies",
)

def _marksheet_subject_order(subjects):
    # MarkSheet-only curriculum order. Do NOT change the database query here:
    # the MarkSheet must first load all subjects exactly as before, then this
    # function orders the already-loaded rows without affecting classes,
    # streams, marks, summaries, or combined-grade selection.
    def normalize(value):
        value = str(value or "").strip().casefold()
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return " ".join(value.split())

    preferred = {
        normalize("English"): 1,
        normalize("Kiswahili"): 2,
        normalize("Mathematics"): 3,
        normalize("Integrated Science"): 4,
        normalize("Agriculture"): 5,
        normalize("Creative Arts and Sports"): 6,
        normalize("Social Studies"): 7,
        normalize("CRE"): 8,
        normalize("Pre-technical Studies"): 9,
    }

    def curriculum_position(value):
        name = normalize(value)
        if name in preferred:
            return preferred[name]

        # Match common stored-name variations without depending on exact
        # punctuation, ampersands, hyphens, or extra descriptors.
        tokens = set(name.split())
        if "english" in tokens:
            return 1
        if "kiswahili" in tokens:
            return 2
        if "mathematics" in tokens or "math" in tokens:
            return 3

        # Integrated Science must be position 4 whenever the stored subject
        # contains both "integrated" and "science", regardless of any other
        # words such as technology, CBC, & etc.
        if "integrated" in tokens and "science" in tokens:
            return 4

        if "agriculture" in tokens:
            return 5
        if "creative" in tokens and "arts" in tokens and "sport" in tokens:
            return 6
        if "social" in tokens and "studies" in tokens:
            return 7
        if name == "cre" or "cre" in tokens:
            return 8
        if "pre" in tokens and "technical" in tokens:
            return 9

        return 100

    # Python's sort is stable, so subjects with the same curriculum position
    # retain their original database order. Other subjects remain after the
    # nine required curriculum subjects, ordered by their normalized name.
    return sorted(
        subjects,
        key=lambda subject: (
            curriculum_position(subject["name"]),
            normalize(subject["name"]) if curriculum_position(subject["name"]) == 100 else "",
        ),
    )

@router.get("/app/academics/marksheets", response_class=HTMLResponse)
def class_marksheets(request: Request, exam_id: str = "", exam_ids: str = "", class_id: str = "", term: str = "", year: str = "", stream: str = ""):
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
        subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
        subjects = _marksheet_subject_order(subjects)
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
    if eid and selected_class_ids:
        class_marks_placeholders = ",".join("?" for _ in selected_class_ids)
        mark_query = "SELECT student_id,subject_id,marks FROM marks WHERE school_id=? AND exam_id=? AND class_id IN (" + class_marks_placeholders + ")"
        mark_params = [sid, eid] + selected_class_ids
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
    streams = sorted(set(str(c["stream"] or "") for c in classes if str(c["stream"] or "")))

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
    for subject in subjects:
        header_cells += "<th colspan='3' class='subjecthead'>%s</th>" % escape(str(subject["name"]))
        sub_header_cells += (
            "<th class='mks-head'>MKS</th>"
            "<th class='grade-head'>GRD</th>"
            "<th class='points-head'>PTS</th>"
        )
        subject_colgroup += (
            "<col class='mks-col' style='width:58px;min-width:58px;max-width:58px'>"
            "<col class='grade-col' style='width:50px;min-width:50px;max-width:50px'>"
            "<col class='points-col' style='width:58px;min-width:58px;max-width:58px'>"
        )

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
            if value is None:
                cells+="<td>—</td><td>—</td><td>—</td>"
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
                cells+=(
                    "<td class='mks-cell'>%.1f</td>"
                    "<td class='grade-cell'><b>%s</b></td>"
                    "<td class='points-cell'>%.1f</td>"
                    % (
                        float(value),
                        escape(str(grade)),
                        float(points),
                    )
                )
        computed.append((student,total,total_points,count,cells))
    computed.sort(key=lambda x:x[1],reverse=True)
    rows=""
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
        rows+=("<tr><td class='adm-no-cell'>%s</td><td class='name-cell'><b>%s</b></td>%s%s"
          "<td><b>%.1f</b></td><td><b>%.1f</b></td><td><b>%.1f%%</b></td><td><b>%s</b></td><td><b>%d</b></td></tr>"
          %(escape(str(student["admission_no"] or "")),escape(str(student["name"] or "")),stream_cell,cells,total,total_points,average,escape(str(overall_grade)),last_position))

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
    doc_brand = "<div class='doc-header'><div class='doc-logo'>%s</div><div><div class='doc-school'>%s</div><div class='doc-contact'>%s%s%s%s</div></div></div>" % (("<img src='%s' alt='School logo'>" % escape(school_logo)) if school_logo else "🏫",school_name,school_email,(" · "+school_phone) if school_phone else "",(" · "+school_postal) if school_postal else "",(" · "+school_postal_code) if school_postal_code else "")
    class_title = escape(str(combined_grade)) + " — ALL STREAMS" if combined_mode and combined_grade else (escape(str(class_row["name"])) if class_row else "Select a class")
    exam_name = escape(" + ".join(str(e["name"]) for e in exams if int(e["id"]) in selected_exam_ids)) if selected_exam_ids else "Select examinations"
    stream_col_html = "<th rowspan='2'>STREAM</th>" if combined_mode else ""
    stream_colgroup_html = "<col class='stream-col'>" if combined_mode else ""
    colspan = 3 + len(subjects) * 3 + 5 if combined_mode else 2 + len(subjects) * 3 + 5
    selected_class_param = quote(str(class_id), safe='') if class_id else quote(str(cid), safe='')
    pdf_marksheet_url = f"<a class='btnlink' href='/app/academics/marksheets/pdf?exam_id={eid}&class_id={selected_class_param}&term={quote(str(term or ''), safe='')}&year={quote(str(year or ''), safe='')}&stream={quote(str(stream or ''), safe='')}'>⬇️ Download PDF</a>"

    print_script = '''<script>
function printDocument(){
  var doc=document.querySelector('.marksheet-card');
  if(!doc){window.print();return;}
  var w=window.open('', '_blank', 'width=1200,height=800');
  if(!w){window.print();return;}
  var generatedAt=new Intl.DateTimeFormat('en-KE',{
    timeZone:'Africa/Nairobi',year:'numeric',month:'2-digit',day:'2-digit',
    hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false
  }).format(new Date())+' EAT';
  var css='*{box-sizing:border-box}body{margin:0;background:#fff;color:#111;font-family:Arial,sans-serif}.marksheet-card{display:block!important;width:100%!important;margin:0!important;padding:0!important;border:0!important;box-shadow:none!important}.no-print{display:none!important}.doc-header{display:flex;align-items:center;gap:14px;border-bottom:2px solid #111827;padding-bottom:10px;margin-bottom:10px}.doc-logo{width:86px;height:70px;display:flex;align-items:center;justify-content:center}.doc-logo img{max-width:82px;max-height:66px;object-fit:contain}.doc-school{font-size:18px;font-weight:900;text-transform:uppercase}.doc-contact{font-size:10px;color:#475569;margin-top:3px}.marksheet-school{text-align:center;font-size:20px;font-weight:900;text-transform:uppercase;padding:6px}.marksheet-meta{font-size:14px;font-weight:800;padding:8px 4px;border-top:1px solid #111;border-bottom:1px solid #111}.marksheet{border-collapse:collapse;width:100%;font-family:Arial,sans-serif;table-layout:fixed}.marksheet th,.marksheet td{border:1px solid #111;padding:4px 5px;text-align:center;font-size:10px;white-space:nowrap}.marksheet th{background:#fff;color:#111}.marksheet .adm-no-col{width:78px}.marksheet .name-col{width:190px;min-width:190px;max-width:190px}.marksheet .stream-col,.marksheet .stream-cell{width:70px;min-width:70px;max-width:70px}.marksheet .mks-col,.marksheet .points-col{width:58px;min-width:58px;max-width:58px}.marksheet .grade-col{width:50px;min-width:50px;max-width:50px}.marksheet .overall-marks-col,.marksheet .overall-points-col{width:62px}.marksheet .overall-avg-col{width:68px}.marksheet .overall-grade-col{width:58px}.marksheet .overall-pos-col{width:50px}.marksheet .subjecthead{font-size:11px;color:#d00;text-transform:uppercase}.marksheet .name-head,.marksheet .name-cell{text-align:left;min-width:190px;width:190px;max-width:190px}.marksheet td b{font-weight:800}.print-footer{position:fixed;left:0;right:0;bottom:0;text-align:center;border-top:1px solid #cbd5e1;padding-top:4px;font-size:8px;color:#475569;background:#fff}@page{size:auto;margin:10mm 10mm 15mm}';
  var footer='<div class="print-footer"><i>DaviSchool Management System</i> · Generated: '+generatedAt+'</div>';
  var html='<!doctype html><html><head><meta charset="utf-8"><title>Class Marksheet</title><style>'+css+'</style></head><body>'+doc.outerHTML+footer+'</body></html>';
  w.document.open();w.document.write(html);w.document.close();w.focus();
  setTimeout(function(){w.print();},300);
}
</script>'''
    subject_mean_html = (
        "<table class='subject-summary'><thead><tr><th>Subject</th><th>Mean</th><th>Entries</th><th>Position</th></tr></thead><tbody>" +
        "".join(
            "<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>"
            % (
                escape(str(subject["name"])),
                ("%.2f" % mean) if mean is not None else "—",
                count,
                str(subject_positions.get(int(subject["id"]), "—")),
            )
            for subject, mean, count in subject_means
        ) +
        "</tbody></table>"
    ) if subject_means else "<div class='subject-mean-empty'>No subject marks available.</div>"
    rows_html = rows or "<tr><td colspan='%d'>No students or marks found.</td></tr>" % colspan
    body = (
        "<div class='page'><h1>Class Marksheets</h1>"
        "<div class='muted'>A print-ready marksheet. Select one or more assessments; when multiple assessments are selected, each subject shows their average.</div>"
        "<div class='card section no-print'><form method='get' action='/app/academics/marksheets' class='marksheet-select'>"
        "<select name='class_id' class='field' onchange='this.form.submit()'><option value=''>Select Class</option>" + copts + "</select>"
        "<select name='stream' class='field' onchange='this.form.submit()'><option value=''>All Streams</option>" + stropts + "</select>"
        "<select name='term' class='field' onchange='this.form.submit()'><option value=''>All Terms</option>" + topts + "</select>"
        "<select name='year' class='field' onchange='this.form.submit()'><option value=''>All Years</option>" + yopts + "</select>"
        "<select name='exam_id' class='field' onchange='this.form.submit()'><option value=''>Select Exam</option>" + eopts + "</select>"
        "<button type='button' class='btn' onclick='printDocument()'>Print Marksheet</button>" + pdf_marksheet_url +
        "</form><div style='margin-top:10px'><a class='btnlink' href='/app/academics/marks'>Enter / Edit Marks</a> "
        "<a class='btnlink' href='/app/academics/grading'>Set Subject Grade & Points</a> "
        "<a class='btnlink' href='/app/academics/overall-grading'>Set Overall Grade</a></div></div>"
        "<div class='card section marksheet-card'>" + doc_brand +
        "<div class='marksheet-school'>" + school_name + "</div>"
        "<div class='marksheet-meta'>CLASS: " + class_title + " &nbsp;&nbsp; EXAM: " + exam_name +
        " &nbsp;&nbsp; TERM: " + escape(term or "All") + " &nbsp;&nbsp; YEAR: " + escape(year or "All") + "</div>"
        "<div style='overflow:auto'><table class='marksheet'><colgroup>"
        "<col class='adm-no-col'><col class='name-col'>" + stream_colgroup_html + subject_colgroup +
        "<col class='overall-marks-col'><col class='overall-points-col'><col class='overall-avg-col'><col class='overall-grade-col'><col class='overall-pos-col'>"
        "</colgroup><thead><tr><th rowspan='2' class='adm-no-head'>ADM NO.</th><th rowspan='2' class='name-head'>NAME</th>" +
        stream_col_html + header_cells + "<th colspan='5'>OVERALL</th></tr><tr>" + sub_header_cells +
        "<th>MKS</th><th>PTS</th><th>AVG %</th><th>GRD</th><th>POS</th></tr></thead><tbody>" +
        rows_html + "</tbody></table></div><div class='subject-mean-summary'><div class='subject-mean-title'>SUBJECT MEANS</div>" +
        "<div class='subject-mean-grid'>" + subject_mean_html + "</div></div></div></div>" +
        print_script +
        "<style>"
        ".field{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}"
        ".marksheet-select{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}.btn,.btnlink{padding:10px 14px;border:1px solid #dbe2ea;border-radius:9px;background:#111827;color:#fff;font-weight:800;text-decoration:none;cursor:pointer}.btnlink{background:#fff;color:#172033;margin-right:6px}"
        ".marksheet-card{background:#fff}.doc-header{display:flex;align-items:center;gap:14px;border-bottom:2px solid #111827;padding-bottom:10px;margin-bottom:10px}.doc-logo{width:86px;height:70px;display:flex;align-items:center;justify-content:center}.doc-logo img{max-width:82px;max-height:66px;object-fit:contain}.doc-school{font-size:18px;font-weight:900;text-transform:uppercase}.doc-contact{font-size:10px;color:#475569;margin-top:3px}.marksheet-title{text-align:center;font-size:24px;font-weight:900;color:#111827;padding:4px}.marksheet-school{text-align:center;font-size:22px;font-weight:900;text-transform:uppercase;padding:6px}.marksheet-meta{font-size:14px;font-weight:800;padding:8px 4px;border-top:1px solid #111;border-bottom:1px solid #111}.marksheet{border-collapse:collapse;width:max-content;min-width:0;font-family:Arial,sans-serif;table-layout:fixed}.marksheet th,.marksheet td{border:1px solid #111;padding:6px 8px;text-align:center;font-size:12px;white-space:nowrap;box-sizing:border-box}.marksheet th{background:#fff;color:#111;text-transform:none}.marksheet .adm-no-col{width:78px;min-width:78px;max-width:78px}.marksheet .name-col{width:190px;min-width:190px;max-width:190px}.marksheet .stream-col,.marksheet .stream-cell{width:70px;min-width:70px;max-width:70px}.marksheet .mks-col,.marksheet .points-col{width:58px;min-width:58px;max-width:58px}.marksheet .grade-col{width:50px;min-width:50px;max-width:50px}.marksheet .overall-marks-col,.marksheet .overall-points-col{width:62px}.marksheet .overall-avg-col{width:68px}.marksheet .overall-grade-col{width:58px}.marksheet .overall-pos-col{width:50px}.marksheet .mks-cell,.marksheet .points-cell{vertical-align:middle;width:58px;min-width:58px;max-width:58px}.marksheet .grade-cell{vertical-align:middle;width:50px;min-width:50px;max-width:50px}.marksheet .subjecthead{font-size:13px;color:#d00;text-transform:uppercase;white-space:nowrap;overflow:hidden;max-width:166px}.marksheet .name-head,.marksheet .name-cell{text-align:left;min-width:190px;width:190px;max-width:190px}.marksheet td b{font-weight:800}.subject-mean-summary{margin-top:12px;border:1px solid #111827;padding:9px;background:#fff}.subject-mean-title{font-size:12px;font-weight:900;text-align:center;border-bottom:1px solid #111827;padding-bottom:5px;margin-bottom:7px}.subject-mean-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px}.subject-mean-item{border:1px solid #cbd5e1;padding:6px;text-align:center}.subject-mean-item span{display:block;font-size:10px;font-weight:800;text-transform:uppercase}.subject-mean-item b{display:block;font-size:14px;margin:2px 0}.subject-mean-item small{font-size:8px;color:#64748b}.subject-mean-empty{font-size:10px;color:#64748b;text-align:center;padding:5px}"
        "@media(max-width:900px){.marksheet-select{grid-template-columns:1fr 1fr}}"
        "@media print{body{background:#fff}.side,.top,.no-print,.page>h1,.page>.muted{display:none!important}.main{margin-left:0!important;padding:0!important}.page{padding:0!important;margin:0!important;max-width:none!important}.marksheet-card{display:block!important;border:0!important;box-shadow:none!important;margin:0!important;padding:0!important;width:100%!important}.marksheet-card .doc-header{margin-top:0}.marksheet-title{font-size:20px}.marksheet-school{font-size:20px}.marksheet th,.marksheet td{padding:4px 5px;font-size:10px}}"
        "</style></div>"
    )
    con.close()
    return _school_page(request, "Class Marksheets", body)


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
        s=cur.execute("SELECT COUNT(*) c FROM students WHERE school_id=?",(school_id,)).fetchone()["c"]
        t=cur.execute("SELECT COUNT(*) c FROM teachers WHERE school_id=?",(school_id,)).fetchone()["c"]
        c=cur.execute("SELECT COUNT(*) c FROM classes WHERE school_id=?",(school_id,)).fetchone()["c"]
        fees=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM fee_payments WHERE school_id=?",(school_id,)).fetchone()["v"]
        con.close()
        school_name=school["name"] if school else "School"
        body=f"""<div class='page'><h1>{escape(school_name)}</h1><div class='muted'>Your complete school operating centre.</div>
<div class='grid'><div class='card'><div class='label'>Students</div><div class='kpi'>{s}</div></div><div class='card'><div class='label'>Staff</div><div class='kpi'>{t}</div></div><div class='card'><div class='label'>Classes</div><div class='kpi'>{c}</div></div><div class='card'><div class='label'>Fees received</div><div class='kpi'>KES {fees:,.0f}</div></div></div>
<div class='section'><h2>Daily operations</h2><div class='actions'><a class='action' href='/app/students'><span>🎓</span>Students</a><a class='action' href='/app/academics/marks'><span>📝</span>Record Marks</a><a class='action' href='/app/attendance'><span>✓</span>Attendance</a><a class='action' href='/app/finance'><span>💰</span>Finance</a><a class='action' href='/app/report-cards'><span>📄</span>Report Cards</a><a class='action' href='/app/academics/analysis'><span>📊</span>Analysis</a><a class='action' href='/app/accounting'><span>📚</span>Accounting</a><a class='action' href='/app/users'><span>👤</span>Users</a></div></div>
<div class='section'><h2>Administration</h2><div class='actions'><a class='action' href='/app/school-settings'><span>⚙</span>School Settings</a><a class='action' href='/app/students/promotion'><span>🎓</span>Promotion / Transfer</a><a class='action' href='/app/roles'><span>🔐</span>Roles</a><a class='action' href='/app/audit'><span>🛡</span>Audit Trail</a><a class='action' href='/app/portals'><span>🌐</span>Portals</a></div></div></div>"""
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

def _ensure_academic_locks_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS academic_locks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            cur.execute("ALTER TABLE academic_locks ADD COLUMN %s %s" % (col, definition))
        except Exception:
            pass

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

def _subject_grade_details(cur, school_id, subject_id, mark, grading_rules=None):
    try:
        value = float(mark)
    except Exception:
        return "—", 0, ""
    if grading_rules is not None:
        for rule in grading_rules.get(int(subject_id), []):
            try:
                if float(rule["min_mark"]) <= value <= float(rule["max_mark"]):
                    return str(rule["grade"]), float(rule["points"] or 0), str(rule["performance_comment"] or "")
            except Exception:
                continue
        grade, points = _default_grade_points(value)
        return grade, points, ""
    try:
        _ensure_grading_table(cur)
        rule = cur.execute("""SELECT grade,points,performance_comment FROM subject_grading_rules
            WHERE school_id=? AND subject_id=? AND ? BETWEEN min_mark AND max_mark
            ORDER BY min_mark DESC, id DESC LIMIT 1""",(school_id, subject_id, value)).fetchone()
        if rule:
            return str(rule["grade"]), float(rule["points"] or 0), str(rule["performance_comment"] or "")
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

@router.get("/app/academics/marks", response_class=HTMLResponse)
def marks_page(request: Request, exam_id: str="", class_id: str="", subject_id: str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "marks.view"):
        return HTMLResponse("You do not have permission to view marks.", 403)
    con=_db();cur=con.cursor()
    try:
        exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
        subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    except Exception as exc:
        print("DAVISCHOOL MARKS ACADEMIC LOOKUP FAILED:", repr(exc), flush=True)
        try: con.rollback()
        except Exception: pass
        con.close()
        return HTMLResponse("Academic data is still initializing. Please refresh this page in a few seconds.",503)
    eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    cid=int(class_id) if class_id.isdigit() else (int(classes[0]["id"]) if classes else 0)
    subid=int(subject_id) if subject_id.isdigit() else (int(subjects[0]["id"]) if subjects else 0)
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
            students=cur.execute("""SELECT s.id,s.admission_no,s.name,CASE WHEN m.marks IS NULL THEN '' ELSE CAST(m.marks AS TEXT) END marks
              FROM students s LEFT JOIN marks m ON m.student_id=s.id AND m.exam_id=? AND m.subject_id=? AND m.school_id=?
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
    if locked:
        if role == "school_admin":
            mark_actions = "<form method='post' action='/app/academics/marks/unfinalize' style='display:inline'><input type='hidden' name='exam_id' value='%s'><input type='hidden' name='class_id' value='%s'><input type='hidden' name='subject_id' value='%s'><button class='btn' type='submit'>🔓 Reopen Marks</button></form> <a class='btnlink' href='/app/academics/marks-corrections'>Correction Requests</a>"%(eid,cid,subid)
        elif pending_correction:
            mark_actions = "<span class='muted'>Correction request is awaiting school admin review.</span>"
        else:
            mark_actions = "<form method='post' action='/app/academics/marks/request-correction' style='display:inline'><input type='hidden' name='exam_id' value='%s'><input type='hidden' name='class_id' value='%s'><input type='hidden' name='subject_id' value='%s'><input name='reason' required placeholder='Reason for correction' class='field' style='display:inline-block;width:min(360px,100%%);margin-right:8px'><button class='btn' type='submit'>🔓 Request Correction</button></form>"%(eid,cid,subid)
    else:
        mark_actions = "<form method='post' action='/app/academics/marks/finalize' style='display:inline' onsubmit=\"return confirm('Submit and lock these marks? Further edits will require an approved correction request.');\"><input type='hidden' name='exam_id' value='%s'><input type='hidden' name='class_id' value='%s'><input type='hidden' name='subject_id' value='%s'><button class='btn' type='submit'>🔒 Submit & Lock Marks</button></form>"%(eid,cid,subid) if students else ""
    rows=""
    for x in students:
        mark=x["marks"]
        if mark=="":
            grade,points="—","—"
        else:
            try:
                grade,points,default_comment=_subject_grade_details(cur,sid,subid,mark,{subid:grading_rules})
                if not subject_comments.get(int(x["id"])) and default_comment:
                    subject_comments[int(x["id"])]=default_comment
            except Exception as exc:
                print("DAVISCHOOL MARKS GRADE FALLBACK:", repr(exc), flush=True)
                grade,points=_default_grade_points(float(mark))
        rows+="<tr id='student-%s'><td>%s</td><td><b>%s</b></td><td><input id='mark-%s' name='mark_%s' value='%s' type='number' min='0' max='%s' step='0.01' class='markinput' %s></td><td class='gradecell'>%s</td><td class='pointcell'>%s</td><td><input name='comment_%s' value='%s' class='field commentinput' placeholder='Performance comment' %s></td><td style='white-space:nowrap'>%s</td></tr>"%(x["id"],escape(str(x["admission_no"] or "")),escape(str(x["name"] or "")),x["id"],x["id"],escape(str(mark)),out_of,"disabled" if locked else "",escape(str(grade)),points if points=="—" else "%.1f"%float(points),x["id"],escape(str(subject_comments.get(int(x["id"]), ""))),"disabled" if locked else "",("" if locked else "<button type='button' class='editbtn' onclick=\"document.getElementById('mark-%s').focus();document.getElementById('mark-%s').select();\">✏️ Edit</button><button type='submit' formaction='/app/academics/marks/delete' formmethod='post' name='student_id' value='%s' class='deletebtn' onclick=\"return confirm('Delete this mark for %s? This cannot be undone.');\">🗑️ Delete</button>"%(x["id"],x["id"],x["id"],escape(str(x["name"] or "")).replace("'","&#39;"))))
    con.close()
    body=(
      "<div class='page'><h1>Marks Entry</h1><div class='muted'>Enter marks and DaviSchool will apply the subject's configured grade and point rules automatically.</div>"
      "<div class='card section'><form method='get' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>"
      "<select name='exam_id' class='field'><option value=''>Select examination</option>"+eopts+"</select>"
      "<select name='class_id' class='field'><option value=''>Select class</option>"+copts+"</select>"
      "<select name='subject_id' class='field'><option value=''>Select subject</option>"+sopts+"</select>"
      "<button class='btn'>Load Students</button></form>"
      "<div style='margin-top:10px;padding:10px;background:#f8fafc;border-radius:9px'>"+escape(rule_note)+" "+grading_link+"</div></div>" +
      "<div class='card section'><div style='margin-bottom:10px;padding:10px;background:%s;border-radius:9px;font-weight:800'>%s</div>"
      "<div style='margin-bottom:12px'>%s</div><form method='post' action='/app/academics/marks/save'>"
      "<input type='hidden' name='exam_id' value='%s'><input type='hidden' name='class_id' value='%s'><input type='hidden' name='subject_id' value='%s'>"
      "<table><thead><tr><th>Admission</th><th>Student</th><th>Mark / %s</th><th>Grade</th><th>Points</th><th>Performance Comment</th><th>Actions</th></tr></thead><tbody>%s</tbody></table>%s"
      "</form><div style='margin-top:10px'>%s</div></div></div>"%(( "#fee2e2" if locked else "#f0fdf4"),("🔒 Marks are FINALIZED and locked." if locked else "🟢 Marks are open for editing."),eid,cid,subid,out_of,rows or "<tr><td colspan='7'>Select an examination, class and subject, then load students.</td></tr>",mark_actions)+
      "<style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}.markinput{width:100px;padding:8px;border:1px solid #dbe2ea;border-radius:8px}.btn,.editbtn,.deletebtn{padding:8px 11px;border:0;border-radius:8px;background:#111827;color:#fff;font-weight:800;cursor:pointer;margin-right:5px}.deletebtn{background:#b91c1c}</style>"
      "<script>var gradingRules=%s;document.querySelectorAll('.markinput').forEach(function(el){el.addEventListener('input',function(){var row=el.closest('tr'),mark=parseFloat(el.value),commentCell=row.querySelector('.commentinput');if(isNaN(mark)){row.querySelector('.gradecell').textContent='—';row.querySelector('.pointcell').textContent='—';if(commentCell)commentCell.value='';return;}var grade='E',points=1,comment='';for(var i=0;i<gradingRules.length;i++){if(mark>=gradingRules[i][0]&&mark<=gradingRules[i][1]){grade=gradingRules[i][2];points=gradingRules[i][3];comment=gradingRules[i][4]||'';break;}}if(gradingRules.length===0){if(mark>=80){grade='A';points=12}else if(mark>=75){grade='A-';points=11}else if(mark>=70){grade='B+';points=10}else if(mark>=65){grade='B';points=9}else if(mark>=60){grade='B-';points=8}else if(mark>=55){grade='C+';points=7}else if(mark>=50){grade='C';points=6}else if(mark>=45){grade='C-';points=5}else if(mark>=40){grade='D+';points=4}else if(mark>=30){grade='D';points=3}}row.querySelector('.gradecell').textContent=grade;row.querySelector('.pointcell').textContent=points;if(commentCell && !commentCell.dataset.manual)commentCell.value=comment;});});document.querySelectorAll('.commentinput').forEach(function(el){el.addEventListener('input',function(){el.dataset.manual='1';});});</script>"%js_rules
    )
    return _school_page(request,"Marks Entry",body)

@router.post("/app/academics/marks/save")
async def marks_save(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to edit marks.", 403)
    form=await request.form()
    con=_db();cur=con.cursor();_ensure_academic_locks_table(cur)
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
    try:
        grading_rules=_load_grading_rules(cur,sid)
    except Exception as exc:
        print("DAVISCHOOL MARKS SAVE GRADING FALLBACK:",repr(exc),flush=True)
        grading_rules={}
    for st in students:
        raw=form.get(f"mark_{st['id']}")
        if raw is None or str(raw).strip()=="":
            continue
        try: mark=float(raw); mark_int=int(mark) if mark.is_integer() else mark
        except Exception: continue
        if mark<0 or mark>out_of: continue
        old=cur.execute("SELECT id FROM marks WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=?",(sid,st["id"],subject_id,exam_id)).fetchone()
        if old:
            cur.execute("UPDATE marks SET marks=?,class_id=?,year=?,term=? WHERE id=? AND school_id=?",(mark_int,class_id,exam["year"],exam["term"],old["id"],sid))
        else:
            cur.execute("INSERT INTO marks(school_id,student_id,subject_id,exam_id,class_id,marks,year,term) VALUES(?,?,?,?,?,?,?,?)",(sid,st["id"],subject_id,exam_id,class_id,mark_int,exam["year"],exam["term"]))
        # Subject performance comment is saved with the same student/exam/subject scope.
        if form.get(f"comment_{st['id']}") is not None:
            _ensure_report_card_fields(cur)
            now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
            comment=str(form.get(f"comment_{st['id']}") or "").strip()
            if not comment:
                try:
                    _, _, comment = _subject_grade_details(cur,sid,subject_id,mark,grading_rules)
                except Exception as exc:
                    print("DAVISCHOOL MARKS COMMENT DEFAULT FALLBACK:",repr(exc),flush=True)
                    comment=""
            existing_comment=cur.execute("SELECT id FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=? LIMIT 1",(sid,st["id"],exam_id,subject_id)).fetchone()
            if existing_comment:
                cur.execute("UPDATE subject_performance_comments SET comment=?,updated_at=? WHERE id=? AND school_id=?",(comment,now,existing_comment["id"],sid))
            else:
                cur.execute("INSERT INTO subject_performance_comments(school_id,student_id,exam_id,subject_id,comment,updated_at) VALUES(?,?,?,?,?,?)",(sid,st["id"],exam_id,subject_id,comment,now))
    _audit(cur,sid,request,"MARKS_SAVE",f"Saved marks for exam {exam_id}, class {class_id}, subject {subject_id}")
    con.commit();con.close()
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)

@router.post("/app/academics/marks/delete")
def marks_delete(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...), student_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to delete marks.", 403)
    con=_db();cur=con.cursor();_ensure_academic_locks_table(cur)
    if not _teacher_class_authorized(cur, request, sid, class_id, subject_id):
        con.close(); return HTMLResponse("You are not allocated to this class and subject.",403)
    valid=cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone() and cur.execute("SELECT id FROM students WHERE id=? AND school_id=? AND class_id=?",(student_id,sid,class_id)).fetchone()
    if not valid:
        con.close(); return HTMLResponse("Invalid academic selection. <a href='/app/academics/marks'>Back</a>",400)
    if _academic_lock(cur,sid,exam_id,class_id,subject_id):
        con.close(); return HTMLResponse("These marks are finalized and locked. <a href='/app/academics/marks'>Back</a>",403)
    row=cur.execute("SELECT id FROM marks WHERE school_id=? AND student_id=? AND subject_id=? AND exam_id=? AND class_id=? ORDER BY id DESC LIMIT 1",(sid,student_id,subject_id,exam_id,class_id)).fetchone()
    if row:
        cur.execute("DELETE FROM marks WHERE id=? AND school_id=?",(row["id"],sid))
        try:
            _ensure_report_card_fields(cur)
            cur.execute("DELETE FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=?",(sid,student_id,exam_id,subject_id))
        except Exception:
            pass
        _audit(cur,sid,request,"MARKS_DELETE",f"Deleted mark for student {student_id}, exam {exam_id}, class {class_id}, subject {subject_id}")
    con.commit();con.close()
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)

@router.post("/app/academics/marks/finalize")
def finalize_marks(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to finalize marks.", 403)
    con=_db();cur=con.cursor();_ensure_academic_locks_table(cur)
    valid=cur.execute("SELECT id FROM exams WHERE id=? AND school_id=?",(exam_id,sid)).fetchone() and cur.execute("SELECT id FROM classes WHERE id=? AND school_id=?",(class_id,sid)).fetchone() and cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if not valid:
        con.close(); return HTMLResponse("Invalid academic selection. <a href='/app/academics/marks'>Back</a>",400)
    if not _teacher_class_authorized(cur, request, sid, class_id, subject_id):
        con.close(); return HTMLResponse("You are not allocated to this class and subject.",403)
    if not _academic_lock(cur,sid,exam_id,class_id,subject_id):
        now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO academic_locks(school_id,exam_id,class_id,subject_id,status,finalized_by,finalized_at) VALUES(?,?,?,?,?,?,?)",(sid,exam_id,class_id,subject_id,"finalized",request.session.get("email",""),now))
        _audit(cur,sid,request,"MARKS_FINALIZE",f"Finalized marks for exam {exam_id}, class {class_id}, subject {subject_id}")
    con.commit();con.close()
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)

@router.post("/app/academics/marks/request-correction")
def request_marks_correction(request: Request, exam_id:int=Form(...), class_id:int=Form(...), subject_id:int=Form(...), reason:str=Form(...)):
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
    cur.execute("INSERT INTO marks_correction_requests(school_id,exam_id,class_id,subject_id,teacher_id,requested_by,requested_at,reason,status) VALUES(?,?,?,?,?,?,?,?,?)",(sid,exam_id,class_id,subject_id,int(teacher_id),request.session.get("email",""),now,reason,"pending"))
    _audit(cur,sid,request,"MARKS_CORRECTION_REQUEST",f"Requested mark correction for exam {exam_id}, class {class_id}, subject {subject_id}: {reason}")
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
        cur.execute("DELETE FROM academic_locks WHERE id=? AND school_id=?",(lock["id"],sid))
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
        cur.execute("DELETE FROM academic_locks WHERE id=? AND school_id=?",(row["id"],sid))
        _audit(cur,sid,request,"MARKS_UNFINALIZE",f"Reopened marks for exam {exam_id}, class {class_id}, subject {subject_id}")
    con.commit();con.close()
    return RedirectResponse(f"/app/academics/marks?exam_id={exam_id}&class_id={class_id}&subject_id={subject_id}",303)

@router.get("/app/academics/analysis", response_class=HTMLResponse)
def new_analysis(request: Request, exam_id:str="", class_id:str=""):
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
    eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    cid=int(class_id) if class_id.isdigit() else (int(classes[0]["id"]) if classes else 0)
    try: grading_rules = _load_grading_rules(cur, sid)
    except Exception as exc:
        print("DAVISCHOOL ANALYSIS GRADING RULES FALLBACK:", repr(exc), flush=True); grading_rules=[]
    try: overall_rules = _load_overall_grading_rules(cur, sid)
    except Exception as exc:
        print("DAVISCHOOL ANALYSIS OVERALL RULES FALLBACK:", repr(exc), flush=True); overall_rules=[]
    stats=[]; student_results=[]
    if eid:
        q="""SELECT sub.id subject_id,sub.name subject,COUNT(m.id) entries,COALESCE(AVG(m.marks),0) avg_mark,
          COALESCE(MAX(m.marks),0) high,COALESCE(MIN(m.marks),0) low
          FROM subjects sub LEFT JOIN marks m ON m.subject_id=sub.id AND m.exam_id=? AND m.school_id=?
          LEFT JOIN students sm ON sm.id=m.student_id AND sm.school_id=m.school_id"""
        params=[eid,sid]
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
                result=_student_result(cur,sid,int(st["id"]),eid,grading_rules,overall_rules)
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
    eopts="".join(f"<option value='{e['id']}' {'selected' if e['id']==eid else ''}>{escape(str(e['name']))}</option>" for e in exams)
    copts="".join(f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    rows="".join(f"<tr><td>{escape(str(x['subject']))}</td><td>{x['entries']}</td><td>{float(x['avg_mark'] or 0):.2f}</td><td>{x['high']}</td><td>{x['low']}</td></tr>" for x in stats)
    ranked=sorted(student_results,key=lambda z:(-float(z[1]["total"]),str(z[0]["name"])))
    rank_map={int(z[0]["id"]):i+1 for i,z in enumerate(ranked)}
    student_rows="".join(f"<tr><td>{escape(str(st['admission_no'] or ''))}</td><td>{escape(str(st['name']))}</td><td>{res['count']}</td><td>{res['total']:.1f}</td><td>{res['average']:.1f}%</td><td>{escape(str(res['overall_grade']))}</td><td>{rank_map.get(int(st['id']),'—')} / {len(ranked)}</td></tr>" for st,res,_ in student_results)
    body=f"""<div class='page'><h1>Academic Analysis</h1><div class='muted'>Analysis uses the same configured grading and points engine used by report cards.</div><div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_ids' class='field' multiple size='3'>{eopts}</select><select name='class_id' class='field'><option value=''>All classes</option>{copts}</select><button class='btn'>Analyse</button></form></div><div class='card section'><h2>Subject Performance</h2><table><thead><tr><th>Subject</th><th>Entries</th><th>Average</th><th>Highest</th><th>Lowest</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No marks found.</td></tr>'}</tbody></table></div><div class='card section'><h2>Student Results</h2><table><thead><tr><th>Admission</th><th>Student</th><th>Subjects</th><th>Total</th><th>Average</th><th>Overall Grade</th><th>Position</th></tr></thead><tbody>{student_rows or '<tr><td colspan=7>No student results found.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Academic Analysis",body)

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
@router.get("/app/report-cards", response_class=HTMLResponse)
def report_cards(request: Request, exam_id:str="", student_id:str="", class_id:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view report cards.", 403)
    con=_db();cur=con.cursor();_ensure_report_card_fields(cur)
    exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    students=cur.execute("SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.name",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    cid=int(class_id) if class_id.isdigit() else 0
    eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    stid=int(student_id) if student_id.isdigit() else (int(students[0]["id"]) if students else 0)
    st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(stid,sid)).fetchone()
    rows=[];comment=""; class_teacher_comment=""; subject_comments={}; opening_date=""; closing_date=""; report_final=False; position="—"; class_total_students=0
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
            sc=cur.execute("SELECT comment FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=? LIMIT 1",(sid,stid,eid,sr["subject_id"])).fetchone()
            saved_comment=(sc["comment"] if sc else "") or ""
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
    result=_student_result(cur,sid,stid,eid) if st and eid else {"rows":[],"details":[],"total":0.0,"points":0.0,"count":0,"average":0.0,"overall_grade":"—"}
    total=result["total"];avg=result["average"]
    markrows="".join(f"<tr><td>{escape(str(r['name']))}</td><td>{mark:.1f}</td><td>{escape(str(grade))}</td><td>{points:.1f}</td></tr>" for r,mark,grade,points in result["details"])
    school_row=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
    school_name=escape(str(school_row["name"] or "DaviSchool")) if school_row else "DaviSchool"
    school_email=escape(str(school_row["email"] or "")) if school_row else ""
    school_phone=escape(str(school_row["phone"] or "")) if school_row else ""
    school_postal=escape("P.O. Box %s" % str(school_row["postal_address"] or "")) if school_row and "postal_address" in school_row.keys() and school_row["postal_address"] else ""
    school_postal_code=escape(str(school_row["postal_code"] or "")) if school_row and "postal_code" in school_row.keys() else ""
    school_logo=str(school_row["logo_data"] or "") if school_row and "logo_data" in school_row.keys() else ""
    doc_brand="<div class='doc-header'><div class='doc-logo'>%s</div><div><div class='doc-school'>%s</div><div class='doc-contact'>%s%s%s%s</div></div></div>" % (("<img src='%s' alt='School logo'>" % escape(school_logo)) if school_logo else "🏫",school_name,school_email,(" · "+school_phone) if school_phone else "",(" · "+school_postal) if school_postal else "",(" · "+school_postal_code) if school_postal_code else "")
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
  var css='*{box-sizing:border-box}body{margin:0;background:#fff;color:#111;font-family:Arial,sans-serif}.report-document{display:block!important;width:100%!important;margin:0!important;padding:0!important;border:0!important;box-shadow:none!important}.no-print{display:none!important}.doc-header{display:flex;align-items:center;gap:14px;border-bottom:2px solid #111827;padding-bottom:10px;margin-bottom:10px}.doc-logo{width:86px;height:70px;display:flex;align-items:center;justify-content:center}.doc-logo img{max-width:82px;max-height:66px;object-fit:contain}.doc-school{font-size:18px;font-weight:900;text-transform:uppercase}.doc-contact{font-size:10px;color:#475569;margin-top:3px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #111;padding:6px;font-size:10px;text-align:left}.kpi{font-size:18px;font-weight:900}.card{border:0;box-shadow:none}.report-comment-form{display:none}.print-footer{position:fixed;left:0;right:0;bottom:0;text-align:center;border-top:1px solid #cbd5e1;padding-top:4px;font-size:8px;color:#475569;background:#fff}@page{size:A4;margin:10mm 10mm 15mm}';
  var footer='<div class="print-footer"><i>DaviSchool Management System</i> · Generated: '+generatedAt+'</div>';
  var html='<!doctype html><html><head><meta charset="utf-8"><title>Student Report Card</title><style>'+css+'</style></head><body>'+doc.outerHTML.replace('id="report"','class="report-document"')+footer+'</body></html>';
  w.document.open();w.document.write(html);w.document.close();w.focus();
  setTimeout(function(){w.print();},300);
}
</script>""";
    bulk_btn=(f"<div style='margin-top:10px'><a class='btn' style='display:inline-block;text-decoration:none' href='/app/report-cards/class-pdf?exam_id={eid}&class_id={cid}'>⬇️ Download All Class Report Cards</a> <a class='btn' style='display:inline-block;text-decoration:none' target='_blank' href='/app/report-cards/class-pdf?exam_id={eid}&class_id={cid}&inline=1'>🖨️ Print All Class Report Cards</a></div>" if cid and eid else "")
    print_btn=(("<button class='btn' style='margin-top:8px' onclick='printReportCard()'>Print Report</button> " if report_final else "") + "<a class='btn' style='display:inline-block;margin-top:8px;text-decoration:none' href='/app/report-cards/pdf?exam_id={eid}&student_id={stid}'>⬇️ Download PDF</a>") if st and eid else ""
    report_html=f"""<div class='card section' id='report' style='background:white'>{doc_brand}<h2>{escape(str(st['name']))}</h2><div class='muted'>Admission: {escape(str(st['admission_no'] or ''))} · Class: {escape(str(st['class_name'] or ''))} {escape(str(st['stream'] or ''))}</div>{final_banner}<table style='margin-top:14px'><thead><tr><th>Subject</th><th>Mark</th><th>Grade</th><th>Points</th><th>Performance Comment</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r['name']))}</td><td>{mark:.1f}</td><td>{escape(str(grade))}</td><td>{points:.1f}</td><td>{escape(str(subject_comments.get(int(r['subject_id']),'')))}</td></tr>" for r,mark,grade,points in result["details"])}</tbody></table><div class='grid'><div class='card'><div class='label'>Subjects</div><div class='kpi'>{len(rows)}</div></div><div class='card'><div class='label'>Total</div><div class='kpi'>{total:.1f}</div></div><div class='card'><div class='label'>Average</div><div class='kpi'>{avg:.1f}%</div></div><div class='card'><div class='label'>Points</div><div class='kpi'>{result["points"]:.1f}</div></div><div class='card'><div class='label'>Overall Grade</div><div class='kpi'>{escape(str(result["overall_grade"]))}</div></div><div class='card'><div class='label'>Position</div><div class='kpi'>{position} / {class_total_students}</div></div></div><div class='report-comment-form'><form method='post' action='/app/report-cards/comment'><input type='hidden' name='exam_id' value='{eid}'><input type='hidden' name='student_id' value='{stid}'><textarea name='comment' class='field' rows='3' placeholder='Teacher / principal comment'>{escape(str(comment or ''))}</textarea><button class='btn' style='margin-top:8px'>Save Comment</button></form></div><div style='margin-top:14px'><b>Class Teacher's Comment</b><div style='border:1px solid #cbd5e1;border-radius:8px;padding:10px;min-height:55px'>{escape(str(class_teacher_comment or ''))}</div></div><div class='grid' style='margin-top:12px'><div><b>Date of Opening</b><div>{escape(str(opening_date or ''))}</div></div><div><b>Date of Closing</b><div>{escape(str(closing_date or ''))}</div></div></div><div style='margin-top:14px'><b>Additional Report Comment</b><div style='border:1px solid #cbd5e1;border-radius:8px;padding:10px;min-height:45px'>{escape(str(comment or ''))}</div></div>{print_btn}{print_script}</div>""" if st else "<div class='card section'>Select a student and examination.</div>"
    subject_editor="".join(f"""<div class='card' style='margin-top:10px'><div style='font-weight:800;margin-bottom:7px'>{escape(str(r['name']))}</div><form method='post' action='/app/report-cards/subject-comment'><input type='hidden' name='student_id' value='{stid}'><input type='hidden' name='exam_id' value='{eid}'><input type='hidden' name='subject_id' value='{r['subject_id']}'><textarea name='comment' class='field' rows='2' placeholder='Performance comment for this subject'>{escape(str(subject_comments.get(int(r['subject_id']),'')))}</textarea><button class='btn' style='margin-top:7px'>Save Subject Comment</button></form></div>""" for r in rows) if st and eid else ""
    teacher_editor=f"""<div class='card section no-print'><h2>Class Teacher's Comment</h2><form method='post' action='/app/report-cards/class-teacher-comment'><input type='hidden' name='student_id' value='{stid}'><input type='hidden' name='exam_id' value='{eid}'><textarea name='comment' class='field' rows='4' placeholder='Enter the class teacher's comment'>{escape(str(class_teacher_comment or ''))}</textarea><button class='btn' style='margin-top:8px'>Save Class Teacher Comment</button></form></div>""" if st and eid else ""
    body=f"""<div class='page'><h1>Report Cards</h1><div class='muted'>Generate a print-ready student academic report.</div><div class='muted' style='margin-top:4px'>Printable and downloadable documents include the DaviSchool Management System footer and exact generation time.</div><div class='card section no-print'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_id' class='field'>{eopts}</select><select name='class_id' class='field'><option value=''>Choose class for bulk report cards</option>{copts}</select><select name='student_id' class='field'><option value=''>Choose individual student (optional)</option>{sopts}</select><button class='btn'>Generate</button></form>{bulk_btn}</div>{report_html}{teacher_editor}<div class='card section no-print'><h2>Subject Performance Comments</h2><div class='muted'>Enter an individual performance comment for each subject. These comments appear on the printed report card.</div>{subject_editor or '<div class="muted" style="margin-top:10px">Select a student and examination first.</div>'}</div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff}}@media print{{.no-print{{display:none!important}}}}</style>"""
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
def subject_analysis_page(request: Request, exam_id: str = "", class_id: str = ""):
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
        eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
        cid=int(class_id) if class_id.isdigit() else 0
        stats=[]
        if eid:
            sql="""SELECT sub.id,sub.name subject,COUNT(m.id) entries,
                    COALESCE(AVG(m.marks),0) average,
                    COALESCE(MAX(m.marks),0) highest,
                    COALESCE(MIN(m.marks),0) lowest
                   FROM subjects sub
                   LEFT JOIN marks m ON m.subject_id=sub.id AND m.exam_id=? AND m.school_id=?
                   LEFT JOIN students st ON st.id=m.student_id AND st.school_id=m.school_id
                   WHERE sub.school_id=?"""
            params=[eid,sid,sid]
            if cid:
                sql+=" AND st.class_id=?"
                params.append(cid)
            sql+=" GROUP BY sub.id,sub.name ORDER BY sub.name"
            stats=cur.execute(sql,params).fetchall()
    except Exception as exc:
        print("DAVISCHOOL SUBJECT ANALYSIS PAGE FAILED:",repr(exc),flush=True)
        try: con.rollback()
        except Exception: pass
        exams=[]; classes=[]; subjects=[]; eid=0; cid=0; stats=[]
    finally:
        con.close()
    eopts="".join(f"<option value='{e['id']}' {'selected' if int(e['id'])==eid else ''}>{escape(str(e['name']))} {escape(str(e['year'] or ''))}</option>" for e in exams)
    copts="".join(f"<option value='{c['id']}' {'selected' if int(c['id'])==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    subject_comment_rules=_load_grading_rules(cur,sid) if stats else {}
    rows="".join(f"<tr><td>{escape(str(r['subject']))}</td><td>{int(r['entries'] or 0)}</td><td>{float(r['average'] or 0):.2f}</td><td>{float(r['highest'] or 0):.1f}</td><td>{float(r['lowest'] or 0):.1f}</td><td>{escape(str(_subject_grade_details(cur,sid,int(r['id']),float(r['average'] or 0),subject_comment_rules)[2] or ''))}</td></tr>" for r in stats)
    body=f"""<div class='page'><h1>Subject Analysis</h1><div class='muted'>Compare subject performance for the selected examination and class.</div>
<div class='card section'><form method='get' action='/app/academics/subject-analysis' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_id' class='field'><option value=''>Select examination</option>{eopts}</select><select name='class_id' class='field'><option value=''>All classes</option>{copts}</select><button class='btn'>Analyse</button></form></div>
<div class='card section'><table><thead><tr><th>Subject</th><th>Entries</th><th>Average</th><th>Highest</th><th>Lowest</th><th>Performance Comment</th></tr></thead><tbody>{rows or "<tr><td colspan='6'>No marks found for the selected examination/class.</td></tr>"}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}}</style>"""
    return _school_page(request,"Subject Analysis",body)

@router.get("/app/academics/student-analysis", response_class=HTMLResponse)
def student_analysis_page(request: Request, exam_id: str = "", student_id: str = ""):
    sid=_school_session(request)
    if not sid: return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view student analysis.", 403)
    con=_db(); cur=con.cursor()
    exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
    students=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.name",(sid,)).fetchall()
    eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
    stid=int(student_id) if student_id.isdigit() else (int(students[0]["id"]) if students else 0)
    st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(stid,sid)).fetchone()
    result=_student_result(cur,sid,stid,eid) if st and eid else {"details":[],"total":0.0,"points":0.0,"count":0,"average":0.0,"overall_grade":"—"}
    con.close()
    eopts="".join(f"<option value='{e['id']}' {'selected' if int(e['id'])==eid else ''}>{escape(str(e['name']))} {escape(str(e['year'] or ''))}</option>" for e in exams)
    sopts="".join(f"<option value='{s['id']}' {'selected' if int(s['id'])==stid else ''}>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    analysis_grading_rules=_load_grading_rules(cur,sid) if st and eid else {}
    rows="".join(f"<tr><td>{escape(str(r['name']))}</td><td>{mark:.1f}</td><td>{escape(str(grade))}</td><td>{points:.1f}</td><td>{escape(str(_subject_grade_details(cur,sid,int(r['subject_id']),mark,analysis_grading_rules)[2] or ''))}</td></tr>" for r,mark,grade,points in result["details"])
    body=f"""<div class='page'><h1>Student Analysis</h1><div class='muted'>Detailed performance for one learner using the same grading engine as the report card.</div>
<div class='card section'><form method='get' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_id' class='field'>{eopts}</select><select name='student_id' class='field'>{sopts}</select><button class='btn'>Analyse</button><a class='btn' style='text-decoration:none;text-align:center' href='/app/academics/student-analysis/pdf?exam_id={eid}&student_id={stid}'>⬇️ Download PDF</a></form></div>
<div class='grid'><div class='card'><div class='label'>Student</div><div class='kpi' style='font-size:18px'>{escape(str(st["name"] if st else "—"))}</div></div><div class='card'><div class='label'>Total</div><div class='kpi'>{result["total"]:.1f}</div></div><div class='card'><div class='label'>Average</div><div class='kpi'>{result["average"]:.1f}%</div></div><div class='card'><div class='label'>Overall Grade</div><div class='kpi'>{escape(str(result["overall_grade"]))}</div></div></div>
<div class='card section'><h2>Subject Results</h2><table><thead><tr><th>Subject</th><th>Mark</th><th>Grade</th><th>Points</th><th>Performance Comment</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No marks recorded for this student and examination.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Student Analysis",body)


@router.get("/app/academics/class-analysis", response_class=HTMLResponse)
def class_analysis_page(request: Request, exam_id: str = "", class_id: str = ""):
    sid=_school_session(request)
    if not sid:
        return RedirectResponse("/")
    if not _require_permission(request, sid, "reports.view"):
        return HTMLResponse("You do not have permission to view class analysis.", 403)
    con=_db(); cur=con.cursor()
    try:
        exams=cur.execute("SELECT id,name,year,term FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        classes=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
        eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
        cid=int(class_id) if class_id.isdigit() else 0
        stats=[]; ranking=[]
        if eid and cid:
            stats=cur.execute("""SELECT sub.id subject_id,sub.name subject,COUNT(m.id) entries,COALESCE(AVG(m.marks),0) average,
                COALESCE(MAX(m.marks),0) highest,COALESCE(MIN(m.marks),0) lowest
                FROM subjects sub LEFT JOIN marks m ON m.subject_id=sub.id AND m.exam_id=? AND m.school_id=?
                LEFT JOIN students st ON st.id=m.student_id AND st.school_id=m.school_id
                WHERE sub.school_id=? AND st.class_id=? GROUP BY sub.id,sub.name ORDER BY sub.name""",
                (eid,sid,sid,cid)).fetchall()
            students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? AND class_id=? ORDER BY name",(sid,cid)).fetchall()
            for st in students:
                try:
                    res=_student_result(cur,sid,int(st["id"]),eid)
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
    eopts="".join(f"<option value='{e['id']}' {'selected' if int(e['id'])==eid else ''}>{escape(str(e['name']))} {escape(str(e['year'] or ''))}</option>" for e in exams)
    copts="".join(f"<option value='{c['id']}' {'selected' if int(c['id'])==cid else ''}>{escape(str(c['name']))} {escape(str(c['stream'] or ''))}</option>" for c in classes)
    class_comment_rules=_load_grading_rules(cur,sid) if stats else {}
    ar="".join(f"<tr><td>{escape(str(x['subject']))}</td><td>{int(x['entries'] or 0)}</td><td>{float(x['average'] or 0):.2f}</td><td>{float(x['highest'] or 0):.1f}</td><td>{float(x['lowest'] or 0):.1f}</td><td>{escape(str(_subject_grade_details(cur,sid,int(x['subject_id']),float(x['average'] or 0),class_comment_rules)[2] or ''))}</td></tr>" for x in stats)
    sr="".join(f"<tr><td>{i}</td><td>{escape(str(st['admission_no'] or ''))}</td><td>{escape(str(st['name']))}</td><td>{res['total']:.1f}</td><td>{res['average']:.1f}%</td><td>{escape(str(res['overall_grade']))}</td></tr>" for i,(st,res) in enumerate(ranking,1))
    body=f"""<div class='page'><h1>Class Analysis</h1><div class='muted'>Class-level subject performance and learner results.</div>
<div class='card section'><form method='get' action='/app/academics/class-analysis' style='display:grid;grid-template-columns:1fr 1fr auto;gap:10px'><select name='exam_id' class='field'><option value=''>Select examination</option>{eopts}</select><select name='class_id' class='field'><option value=''>Select class</option>{copts}</select><button class='btn'>Analyse</button></form></div>
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
    users=cur.execute("""SELECT u.*,t.name teacher_name,s.name student_name
        FROM users u LEFT JOIN teachers t ON t.id=u.teacher_id LEFT JOIN students s ON s.id=u.student_id
        WHERE u.school_id=? ORDER BY u.id DESC""",(sid,)).fetchall()
    teachers=cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    con.close()
    rows="".join(f"<tr><td>{escape(str(u['full_name'] or ''))}</td><td>{escape(str(u['email'] or ''))}</td><td>{escape(str(u['role'] or ''))}</td><td>{escape(str(u['teacher_name'] or u['student_name'] or '—'))}</td></tr>" for u in users)
    topts="".join(f"<option value='{t['id']}'>{escape(str(t['name']))}</option>" for t in teachers)
    sopts="".join(f"<option value='{s['id']}'>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    body=f"""<div class='page'><h1>User Management</h1><div class='muted'>Create school accounts and link them to staff or students.</div>
<div class='card section'><h2>Create user</h2><form method='post' action='/app/users/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>
<input name='full_name' required placeholder='Full name' class='field'><input name='email' type='email' required placeholder='Email' class='field'><input name='password' type='password' required minlength='8' placeholder='Temporary password' class='field'>
<select name='role' class='field'><option value='school_admin'>School Admin</option><option value='teacher'>Teacher</option><option value='parent'>Parent</option><option value='student'>Student</option><option value='accountant'>Accountant</option><option value='registrar'>Registrar</option></select>
<select name='teacher_id' class='field'><option value=''>Link teacher (optional)</option>{topts}</select><select name='student_id' class='field'><option value=''>Link student (optional)</option>{sopts}</select>
<button class='btn'>Create Account</button></form></div>
<div class='card section'><h2>Accounts ({len(users)})</h2><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Linked profile</th></tr></thead><tbody>{rows or '<tr><td colspan=4>No users yet.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"User Management",body)

@router.post("/app/users/add")
def users_add(request: Request, full_name:str=Form(...), email:str=Form(...), password:str=Form(...), role:str=Form("teacher"), teacher_id:str=Form(""), student_id:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "users.manage"):
        return HTMLResponse("You do not have permission to manage users.", 403)
    if len(password)<8:return HTMLResponse("Password must be at least 8 characters. <a href='/app/users'>Back</a>",400)
    allowed={"school_admin","teacher","parent","student","accountant","registrar"}
    if role not in allowed:return HTMLResponse("Invalid role. <a href='/app/users'>Back</a>",400)
    con=_db();cur=con.cursor()
    email_v=email.strip().lower()
    if cur.execute("SELECT id FROM users WHERE lower(email)=?",(email_v,)).fetchone():
        con.close();return HTMLResponse("Email already exists. <a href='/app/users'>Back</a>",400)
    tid=int(teacher_id) if teacher_id.isdigit() else None
    stid=int(student_id) if student_id.isdigit() else None
    if tid and not cur.execute("SELECT id FROM teachers WHERE id=? AND school_id=?",(tid,sid)).fetchone():
        con.close();return HTMLResponse("Selected teacher does not belong to this school. <a href='/app/users'>Back</a>",400)
    if stid and not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(stid,sid)).fetchone():
        con.close();return HTMLResponse("Selected student does not belong to this school. <a href='/app/users'>Back</a>",400)
    if role=="teacher" and not tid:
        con.close();return HTMLResponse("Teacher accounts must be linked to a teacher profile. <a href='/app/users'>Back</a>",400)
    if role in ("student","parent") and not stid:
        con.close();return HTMLResponse("Student and parent accounts must be linked to a student profile. <a href='/app/users'>Back</a>",400)
    if role not in ("teacher","student","parent") and (tid or stid):
        con.close();return HTMLResponse("This role cannot be linked to a teacher or student profile. <a href='/app/users'>Back</a>",400)
    from app.main import hash_password
    cur.execute("INSERT INTO users(email,password,role,full_name,school_id,teacher_id,student_id) VALUES(?,?,?,?,?,?,?)",(email_v,hash_password(password),role,full_name.strip(),sid,tid,stid))
    _audit(cur,sid,request,"USER_CREATE",f"Created {role} account {email.strip()}")
    con.commit();con.close();return RedirectResponse("/app/users",303)


@router.get("/app/classes", response_class=HTMLResponse)
def classes_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "classes.view"):
        return HTMLResponse("You do not have permission to view classes.", 403)
    con=_db();cur=con.cursor(); rows=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall();con.close()
    trs="".join(f"<tr><td>{escape(str(x['name']))}</td><td>{escape(str(x['level'] or ''))}</td><td>{escape(str(x['stream'] or ''))}</td></tr>" for x in rows)
    body=f"""<div class='page'><h1>Classes & Streams</h1><div class='card section'><form method='post' action='/app/classes/add' class='formgrid'><input name='name' required placeholder='Class name e.g. Grade 6' class='field'><select name='level' class='field'><option value=''>Select level</option><option>Pre-Primary</option><option>Lower Primary</option><option>Upper Primary</option><option>Junior Secondary</option><option>Senior Secondary</option><option>College</option><option>Other</option></select><input name='stream' placeholder='Stream' class='field'><button class='btn'>Add Class</button></form></div><div class='card section'><table><thead><tr><th>Name</th><th>Level</th><th>Stream</th></tr></thead><tbody>{trs or '<tr><td colspan=3>No classes.</td></tr>'}</tbody></table></div></div><style>.formgrid{{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px}}.field{{padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:white;font-weight:800}}</style>"""
    return _school_page(request,"Classes",body)

@router.post("/app/classes/add")
def classes_add(request: Request,name:str=Form(...),level:str=Form(""),stream:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "classes.create"):
        return HTMLResponse("You do not have permission to create classes.", 403)
    name_v=name.strip(); level_v=level.strip(); stream_v=stream.strip()
    if not name_v:return HTMLResponse("Class name is required. <a href='/app/classes'>Back</a>",400)
    con=_db();cur=con.cursor()
    if cur.execute("SELECT id FROM classes WHERE school_id=? AND lower(name)=lower(?) AND lower(COALESCE(stream,''))=lower(?)",(sid,name_v,stream_v)).fetchone():
        con.close();return HTMLResponse("That class and stream already exists. <a href='/app/classes'>Back</a>",400)
    cur.execute("INSERT INTO classes(school_id,name,level,stream) VALUES(?,?,?,?)",(sid,name_v,level_v,stream_v))
    _audit(cur,sid,request,"CLASS_CREATE",name_v);con.commit();con.close();return RedirectResponse("/app/classes",303)

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

@router.get("/app/timetable", response_class=HTMLResponse)
def timetable_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "timetable.view"):
        return HTMLResponse("You do not have permission to view the timetable.", 403)
    con=_db();cur=con.cursor()
    rows=cur.execute("SELECT * FROM timetable WHERE school_id=? ORDER BY day,start_time",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    teachers=cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    con.close()
    co="".join(f"<option>{escape(str(x['name']))} {escape(str(x['stream'] or ''))}</option>" for x in classes)
    streams=sorted({str(x['stream'] or '').strip() for x in classes if str(x['stream'] or '').strip()})
    to="".join(f"<option>{escape(str(x['name']))}</option>" for x in teachers)
    so="".join(f"<option>{escape(str(x['name']))}</option>" for x in subjects)
    stro="".join(f"<option>{escape(x)}</option>" for x in streams)
    tr=_simple_rows(rows,["day","start_time","end_time","class_name","stream","subject","teacher","room"])
    body=f"""<div class='page'><h1>Timetable</h1><div class='muted'>Build and maintain the school timetable.</div>
<div class='card section'><h2>Add lesson</h2><form method='post' action='/app/timetable/add' style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>
<select name='day' class='field'><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option><option>Saturday</option></select><input name='start_time' required type='time' class='field'><input name='end_time' required type='time' class='field'><select name='class_name' class='field'>{co}</select><select name='stream' class='field'><option value=''>Select stream</option>{stro}</select><select name='subject' class='field'>{so}</select><select name='teacher' class='field'>{to}</select><input name='room' placeholder='Room' class='field'><button class='btn'>Save Lesson</button></form></div>
<div class='card section'><h2>Weekly timetable ({len(rows)})</h2><table><thead><tr><th>Day</th><th>Start</th><th>End</th><th>Class</th><th>Stream</th><th>Subject</th><th>Teacher</th><th>Room</th></tr></thead><tbody>{tr or '<tr><td colspan=8>No timetable entries yet.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Timetable",body)

@router.post("/app/timetable/add")
def timetable_add(request: Request,day:str=Form(...),start_time:str=Form(...),end_time:str=Form(...),class_name:str=Form(""),stream:str=Form(""),subject:str=Form(""),teacher:str=Form(""),room:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "timetable.edit"):
        return HTMLResponse("You do not have permission to edit the timetable.", 403)
    if day not in ("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"):
        return HTMLResponse("Invalid timetable day. <a href='/app/timetable'>Back</a>",400)
    if not start_time or not end_time or end_time <= start_time:
        return HTMLResponse("End time must be after start time. <a href='/app/timetable'>Back</a>",400)
    con=_db();cur=con.cursor()
    class_row=cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? AND name=? AND stream=? LIMIT 1",(sid,class_name.strip(),stream.strip())).fetchone()
    subject_row=cur.execute("SELECT id FROM subjects WHERE school_id=? AND name=? LIMIT 1",(sid,subject.strip())).fetchone() if subject.strip() else None
    teacher_row=cur.execute("SELECT id FROM teachers WHERE school_id=? AND name=? LIMIT 1",(sid,teacher.strip())).fetchone() if teacher.strip() else None
    if not class_row:
        con.close(); return HTMLResponse("Invalid class or stream for this school. <a href='/app/timetable'>Back</a>",400)
    if subject.strip() and not subject_row:
        con.close(); return HTMLResponse("Invalid subject for this school. <a href='/app/timetable'>Back</a>",400)
    if teacher.strip() and not teacher_row:
        con.close(); return HTMLResponse("Invalid teacher for this school. <a href='/app/timetable'>Back</a>",400)
    cur.execute("INSERT INTO timetable(school_id,day,start_time,end_time,class_name,stream,subject,teacher,room) VALUES(?,?,?,?,?,?,?,?,?)",(sid,day,start_time,end_time,class_name.strip(),stream.strip(),subject.strip(),teacher.strip(),room.strip()))
    _audit(cur,sid,request,"TIMETABLE_CREATE",f"{day} {start_time}-{end_time} {class_name} {subject}")
    con.commit();con.close();return RedirectResponse("/app/timetable",303)

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
    con=_db();cur=con.cursor();rows=cur.execute("SELECT * FROM roles_permissions WHERE school_id=? ORDER BY role,permission",(sid,)).fetchall();con.close()
    tr=_simple_rows(rows,["role","permission","enabled"])
    body=f"""<div class='page'><h1>Roles & Permissions</h1><div class='muted'>Control permissions for school roles.</div>
<div class='card section'><h2>Grant permission</h2><form method='post' action='/app/roles/add' style='display:grid;grid-template-columns:1fr 2fr 1fr;gap:10px'><select name='role' class='field'><option>school_admin</option><option>teacher</option><option>parent</option><option>student</option><option>accountant</option><option>registrar</option></select><select name='permission' required class='field'><option value=''>Select permission</option><option>students.view</option><option>students.create</option><option>students.edit</option><option>classes.view</option><option>classes.create</option><option>subjects.view</option><option>subjects.create</option><option>exams.view</option><option>exams.create</option><option>marks.view</option><option>marks.edit</option><option>attendance.view</option><option>attendance.edit</option><option>timetable.view</option><option>timetable.edit</option><option>fees.view</option><option>fees.edit</option><option>finance.view</option><option>finance.edit</option><option>reports.view</option><option>reports.edit</option><option>staff.view</option><option>staff.create</option><option>staff.edit</option><option>communications.view</option><option>communications.edit</option><option>settings.view</option><option>settings.edit</option><option>audit.view</option><option>users.manage</option><option>settings.manage</option></select><select name='enabled' class='field'><option value='1'>Enabled</option><option value='0'>Disabled</option></select><button class='btn'>Save Permission</button></form></div>
<div class='card section'><h2>Configured permissions ({len(rows)})</h2><table><thead><tr><th>Role</th><th>Permission</th><th>Enabled</th></tr></thead><tbody>{tr or '<tr><td colspan=3>No custom permissions yet.</td></tr>'}</tbody></table></div></div><style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Roles & Permissions",body)

@router.post("/app/roles/add")
def roles_add(request: Request,role:str=Form(...),permission:str=Form(...),enabled:int=Form(1)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "settings.manage"):
        return HTMLResponse("You do not have permission to manage roles and permissions.", 403)
    allowed_roles={"school_admin","teacher","parent","student","accountant","registrar"}
    allowed_permissions={"students.view","students.create","students.edit","classes.view","classes.create","subjects.view","subjects.create","exams.view","exams.create","marks.view","marks.edit","attendance.view","attendance.edit","timetable.view","timetable.edit","fees.view","fees.edit","finance.view","finance.edit","reports.view","reports.edit","staff.view","staff.create","staff.edit","communications.view","communications.edit","settings.view","settings.edit","audit.view","users.manage","settings.manage"}
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
    con=_db();cur=con.cursor();rows=cur.execute("SELECT * FROM system_audit WHERE school_id=? ORDER BY id DESC LIMIT 500",(sid,)).fetchall();con.close()
    tr=_simple_rows(rows,["timestamp","user_email","action","details"])
    body=f"""<div class='page'><h1>Audit Trail</h1><div class='muted'>Security and activity history for this school.</div><div class='card section'><h2>Recent activity ({len(rows)})</h2><table><thead><tr><th>Timestamp</th><th>User</th><th>Action</th><th>Details</th></tr></thead><tbody>{tr or '<tr><td colspan=4>No activity recorded yet.</td></tr>'}</tbody></table></div></div>"""
    return _school_page(request,"Audit Trail",body)

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
    if not _require_permission(request, sid, "finance.edit"):
        return HTMLResponse("You do not have permission to record expenses.", 403)
    if amount <= 0:
        return HTMLResponse("Expense amount must be greater than zero. <a href='/app/accounting'>Back</a>",400)
    con=_db();cur=con.cursor();cur.execute("INSERT INTO expenses(school_id,category,description,amount,paid_to,voucher_no,date) VALUES(?,?,?,?,?,?,?)",(sid,category.strip(),description.strip(),amount,paid_to.strip(),voucher_no.strip(),date or datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d")))
    _audit(cur,sid,request,"EXPENSE_CREATE",f"{category}: {amount}");con.commit();con.close();return RedirectResponse("/app/accounting",303)


def _ensure_assessment_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS assessment_scores(
        id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER, student_id INTEGER,
        subject_id INTEGER, term TEXT, year TEXT, component TEXT,
        score REAL, out_of REAL, created_at TEXT)""")

@router.get("/app/academics/allocations", response_class=HTMLResponse)
def allocations_page(request: Request):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "staff.edit"):
        return HTMLResponse("You do not have permission to manage teacher allocations.", 403)
    con=_db();cur=con.cursor()
    teachers=cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    rows=cur.execute("""SELECT ta.*,t.name teacher_name,s.name subject_name,c.name class_name,c.stream
                        FROM teacher_allocations ta JOIN teachers t ON t.id=ta.teacher_id
                        JOIN subjects s ON s.id=ta.subject_id JOIN classes c ON c.id=ta.class_id
                        WHERE ta.school_id=? ORDER BY t.name,s.name,c.name""",(sid,)).fetchall()
    con.close()
    opts=lambda xs,label: "".join(f"<option value='{x['id']}'>{escape(str(x['name']))}{(' '+escape(str(x['stream'] or ''))) if label=='class' else ''}</option>" for x in xs)
    tr="".join(
        f"""<tr><td><b>{escape(str(r['teacher_name']))}</b></td>
<td>{escape(str(r['subject_name']))}</td>
<td>{escape(str(r['class_name']))}</td>
<td>{escape(str(r['stream'] or ''))}</td>
<td style='white-space:nowrap'>
<a class='action' href='/app/academics/allocations/edit/{r["id"]}' style='background:#2563eb;color:white;padding:7px 11px;border-radius:7px;text-decoration:none'>✏ Edit</a>
<form method='post' action='/app/academics/allocations/delete/{r["id"]}' style='display:inline;margin-left:6px' onsubmit='return confirm("Delete this teacher allocation? This will remove only this allocation record.")'>
<button type='submit' style='background:#dc2626;color:white;border:0;padding:7px 11px;border-radius:7px;cursor:pointer'>🗑 Delete</button>
</form></td></tr>"""
        for r in rows
    )
    body=f"""<div class='page'><h1>Teacher Allocation</h1><div class='muted'>Assign teachers to subjects and classes.</div>
<div class='card section'><form method='post' action='/app/academics/allocations/add' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>
<select name='teacher_id' required class='field'>{opts(teachers,'teacher')}</select><select name='subject_id' required class='field'>{opts(subjects,'subject')}</select><select name='class_id' required class='field'>{opts(classes,'class')}</select><button class='btn'>Save Allocation</button></form></div>
<div class='card section'><h2>Current allocations ({len(rows)})</h2><table><thead><tr><th>Teacher</th><th>Subject</th><th>Class</th><th>Stream</th><th>Actions</th></tr></thead><tbody>{tr or '<tr><td colspan=5>No allocations yet.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Teacher Allocation",body)

@router.get("/app/academics/allocations/edit/{allocation_id}", response_class=HTMLResponse)
def allocations_edit_page(request: Request, allocation_id: int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "staff.edit"):
        return HTMLResponse("You do not have permission to manage teacher allocations.", 403)
    con=_db();cur=con.cursor()
    row=cur.execute("""SELECT * FROM teacher_allocations
                       WHERE id=? AND school_id=?""",(allocation_id,sid)).fetchone()
    teachers=cur.execute("SELECT * FROM teachers WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
    con.close()
    if not row:
        return HTMLResponse("Teacher allocation not found. <a href='/app/academics/allocations'>Back to Teacher Allocation</a>",404)
    opts_edit=lambda xs,selected: "".join(
        f"<option value='{x['id']}' {'selected' if int(x['id'])==int(selected) else ''}>{escape(str(x['name']))}{(' '+escape(str(x['stream'] or ''))) if 'stream' in x.keys() and x['stream'] else ''}</option>"
        for x in xs
    )
    body=f"""<div class='page'><h1>Edit Teacher Allocation</h1><div class='muted'>Update this allocation without changing any other allocation records.</div>
<div class='card section'><form method='post' action='/app/academics/allocations/edit/{allocation_id}' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>
<select name='teacher_id' required class='field'>{opts_edit(teachers,row['teacher_id'])}</select>
<select name='subject_id' required class='field'>{opts_edit(subjects,row['subject_id'])}</select>
<select name='class_id' required class='field'>{opts_edit(classes,row['class_id'])}</select>
<div style='grid-column:1/-1;display:flex;gap:10px'><button class='btn' type='submit'>Save Changes</button><a href='/app/academics/allocations' class='btn' style='text-decoration:none;background:#64748b'>Cancel</a></div>
</form></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"Edit Teacher Allocation",body)

@router.post("/app/academics/allocations/edit/{allocation_id}")
def allocations_edit(request: Request, allocation_id: int, teacher_id:int=Form(...), subject_id:int=Form(...), class_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "staff.edit"):
        return HTMLResponse("You do not have permission to manage teacher allocations.", 403)
    con=_db();cur=con.cursor()
    current=cur.execute("SELECT id FROM teacher_allocations WHERE id=? AND school_id=?",(allocation_id,sid)).fetchone()
    valid=all(cur.execute(q,(x,sid)).fetchone() for q,x in [
        ("SELECT id FROM teachers WHERE id=? AND school_id=?",teacher_id),
        ("SELECT id FROM subjects WHERE id=? AND school_id=?",subject_id),
        ("SELECT id FROM classes WHERE id=? AND school_id=?",class_id)])
    duplicate=cur.execute("""SELECT id FROM teacher_allocations
                             WHERE school_id=? AND teacher_id=? AND subject_id=? AND class_id=? AND id<>?""",
                          (sid,teacher_id,subject_id,class_id,allocation_id)).fetchone()
    if not current:
        con.close()
        return HTMLResponse("Teacher allocation not found.",404)
    if not valid:
        con.close()
        return HTMLResponse("Invalid teacher, subject or class selection.",400)
    if duplicate:
        con.close()
        return HTMLResponse("That teacher allocation already exists. Choose different details or delete the duplicate record.",400)
    cur.execute("""UPDATE teacher_allocations
                   SET teacher_id=?, subject_id=?, class_id=?
                   WHERE id=? AND school_id=?""",
                (teacher_id,subject_id,class_id,allocation_id,sid))
    _audit(cur,sid,request,"TEACHER_ALLOCATION_EDIT",f"Updated teacher allocation {allocation_id}")
    con.commit();con.close()
    return RedirectResponse("/app/academics/allocations",303)

@router.post("/app/academics/allocations/delete/{allocation_id}")
def allocations_delete(request: Request, allocation_id: int):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "staff.edit"):
        return HTMLResponse("You do not have permission to manage teacher allocations.", 403)
    con=_db();cur=con.cursor()
    row=cur.execute("SELECT id,teacher_id,subject_id,class_id FROM teacher_allocations WHERE id=? AND school_id=?",(allocation_id,sid)).fetchone()
    if not row:
        con.close()
        return HTMLResponse("Teacher allocation not found.",404)
    cur.execute("DELETE FROM teacher_allocations WHERE id=? AND school_id=?",(allocation_id,sid))
    _audit(cur,sid,request,"TEACHER_ALLOCATION_DELETE",f"Deleted teacher allocation {allocation_id}")
    con.commit();con.close()
    return RedirectResponse("/app/academics/allocations",303)

@router.post("/app/academics/allocations/add")
def allocations_add(request: Request,teacher_id:int=Form(...),subject_id:int=Form(...),class_id:int=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "staff.edit"):
        return HTMLResponse("You do not have permission to manage teacher allocations.", 403)
    con=_db();cur=con.cursor()
    valid=all(cur.execute(q,(x,sid)).fetchone() for q,x in [
        ("SELECT id FROM teachers WHERE id=? AND school_id=?",teacher_id),
        ("SELECT id FROM subjects WHERE id=? AND school_id=?",subject_id),
        ("SELECT id FROM classes WHERE id=? AND school_id=?",class_id)])
    if valid:
        if not cur.execute("SELECT id FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND subject_id=? AND class_id=?",(sid,teacher_id,subject_id,class_id)).fetchone():
            cur.execute("INSERT INTO teacher_allocations(school_id,teacher_id,subject_id,class_id) VALUES(?,?,?,?)",(sid,teacher_id,subject_id,class_id))
            _audit(cur,sid,request,"TEACHER_ALLOCATION","Created teacher allocation")
    con.commit();con.close();return RedirectResponse("/app/academics/allocations",303)

@router.get("/app/academics/assessments", response_class=HTMLResponse)
def assessments_page(request: Request, student_id:str="", subject_id:str="", term:str=""):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/")
    if not _require_permission(request, sid, "marks.view"):
        return HTMLResponse("You do not have permission to view assessments.", 403)
    con=_db();cur=con.cursor();_ensure_assessment_table(cur)
    students=cur.execute("SELECT * FROM students WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    subjects=cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(sid,)).fetchall()
    stid=int(student_id) if student_id.isdigit() else 0; subid=int(subject_id) if subject_id.isdigit() else 0
    rows=cur.execute("""SELECT a.*,s.name subject_name FROM assessment_scores a JOIN subjects s ON s.id=a.subject_id
                        WHERE a.school_id=? AND (?=0 OR a.student_id=?) AND (?=0 OR a.subject_id=?) AND (?='' OR a.term=?)
                        ORDER BY a.id DESC LIMIT 300""",(sid,stid,stid,subid,subid,term,term)).fetchall()
    con.commit();con.close()
    so="".join(f"<option value='{s['id']}' {'selected' if s['id']==subid else ''}>{escape(str(s['name']))}</option>" for s in subjects)
    sto="".join(f"<option value='{s['id']}' {'selected' if s['id']==stid else ''}>{escape(str(s['name']))} ({escape(str(s['admission_no'] or ''))})</option>" for s in students)
    tr=_simple_rows(rows,["student_id","subject_name","term","year","component","score","out_of","created_at"])
    body=f"""<div class='page'><h1>SBA / CBA</h1><div class='muted'>Record continuous assessment components separately from examination marks.</div>
<div class='card section'><form method='post' action='/app/academics/assessments/add' style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>
<select name='student_id' required class='field'>{sto}</select><select name='subject_id' required class='field'>{so}</select><input name='term' required placeholder='Term 1' class='field'><input name='year' required value='{datetime.now(ZoneInfo("Africa/Nairobi")).year}' class='field'><input name='component' required placeholder='CAT 1 / Project / SBA' class='field'><input name='score' required type='number' min='0' step='0.01' placeholder='Score' class='field'><input name='out_of' required type='number' min='1' step='0.01' value='100' placeholder='Out of' class='field'><button class='btn'>Save Assessment</button></form></div>
<div class='card section'><h2>Assessment records</h2><table><thead><tr><th>Student ID</th><th>Subject</th><th>Term</th><th>Year</th><th>Component</th><th>Score</th><th>Out Of</th><th>Created</th></tr></thead><tbody>{tr or '<tr><td colspan=8>No assessment records yet.</td></tr>'}</tbody></table></div></div>
<style>.field{{width:100%;padding:11px;border:1px solid #dbe2ea;border-radius:9px}}.btn{{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800}}</style>"""
    return _school_page(request,"SBA / CBA",body)

@router.post("/app/academics/assessments/add")
def assessments_add(request: Request,student_id:int=Form(...),subject_id:int=Form(...),term:str=Form(...),year:str=Form(...),component:str=Form(...),score:float=Form(...),out_of:float=Form(...)):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "marks.edit"):
        return HTMLResponse("You do not have permission to edit assessments.", 403)
    term_v=term.strip()
    year_v=year.strip()
    component_v=component.strip()
    if out_of<=0 or score<0 or score>out_of or not term_v or not year_v or not component_v:
        return HTMLResponse("Invalid assessment details or score. <a href='/app/academics/assessments'>Back</a>",400)
    con=_db();cur=con.cursor();_ensure_assessment_table(cur)
    valid_student=cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(student_id,sid)).fetchone()
    valid_subject=cur.execute("SELECT id FROM subjects WHERE id=? AND school_id=?",(subject_id,sid)).fetchone()
    if not valid_student or not valid_subject:
        con.close()
        return HTMLResponse("Invalid student or subject. <a href='/app/academics/assessments'>Back</a>",400)
    duplicate=cur.execute("""SELECT id FROM assessment_scores
        WHERE school_id=? AND student_id=? AND subject_id=? AND term=? AND year=? AND lower(component)=lower(?) LIMIT 1""",
        (sid,student_id,subject_id,term_v,year_v,component_v)).fetchone()
    if duplicate:
        con.close()
        return HTMLResponse("This assessment component already exists for the selected student, subject, term and year. <a href='/app/academics/assessments'>Back</a>",400)
    cur.execute("INSERT INTO assessment_scores(school_id,student_id,subject_id,term,year,component,score,out_of,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(sid,student_id,subject_id,term_v,year_v,component_v,score,out_of,datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")))
    _audit(cur,sid,request,"ASSESSMENT_SAVE",f"Saved {component_v} for student {student_id}")
    con.commit();con.close();return RedirectResponse("/app/academics/assessments",303)


# PDF downloads for the current school workspace. These endpoints are read-only:
# they query existing records and never modify marks, students, classes or reports.
@router.get("/app/academics/marksheets/pdf")
def class_marksheets_pdf(request: Request, exam_id: str = "", class_id: str = "", term: str = "", year: str = "", stream: str = ""):

    try:
        sid = _school_session(request)
        if not sid:
            return RedirectResponse("/")
        if not _require_permission(request, sid, "reports.view"):
            return HTMLResponse("You do not have permission to download marksheets.", 403)
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A3, landscape
        from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.units import mm
        con = _db(); cur = con.cursor()
        try:
            _ensure_grading_table(cur)
        except Exception as exc:
            print("DAVISCHOOL MARKSHEET PDF GRADING TABLE FALLBACK:", repr(exc), flush=True)
        exams = cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        classes = cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
        subjects = cur.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name", (sid,)).fetchall()
        subjects = _marksheet_subject_order(subjects)
        eid = int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
        combined_mode = class_id.startswith("grade:")
        combined_grade = class_id[6:] if combined_mode else ""
        def _grade_group_key(row):
            name = str(row["name"] or "").strip()
            stream_value = str(row["stream"] or "").strip()
            if stream_value:
                return name
            match = re.match(r"^(.*?\d)\s*[A-Za-z]$", name)
            return match.group(1).strip() if match else name
        if combined_mode:
            selected_class_ids = [
                int(c["id"]) for c in classes
                if _grade_group_key(c).strip().lower() == combined_grade.strip().lower()
            ]
            cid = selected_class_ids[0] if selected_class_ids else 0
            stream = ""
        else:
            cid = int(class_id) if class_id.isdigit() else (int(classes[0]["id"]) if classes else 0)
            selected_class_ids = [cid] if cid else []
        class_stream_by_id = {int(c["id"]): str(c["stream"] or "") for c in classes}
        er = cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?",(eid,sid)).fetchone() if eid else None
        cr = cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?",(cid,sid)).fetchone() if cid else None
        if er:
            term = term or str(er["term"] or "")
            year = year or str(er["year"] or "")
        if selected_class_ids:
            placeholders = ",".join("?" for _ in selected_class_ids)
            q = "SELECT * FROM students WHERE school_id=? AND class_id IN (" + placeholders + ")"
            params=[sid] + selected_class_ids
        else:
            q = "SELECT * FROM students WHERE school_id=? AND class_id=?"; params=[sid,cid]
        if stream and not combined_mode:
            q += " AND stream=?"; params.append(stream)
        students = cur.execute(q+" ORDER BY name",params).fetchall() if selected_class_ids else []
        placeholders = ",".join("?" for _ in selected_class_ids)
        mq="SELECT student_id,subject_id,marks FROM marks WHERE school_id=? AND exam_id=? AND class_id IN (" + placeholders + ")"; mp=[sid,eid] + selected_class_ids
        if term: mq+=" AND term=?"; mp.append(term)
        if year: mq+=" AND year=?"; mp.append(year)
        mark_rows=cur.execute(mq,mp).fetchall() if eid and cid else []
        marks={(int(x["student_id"]),int(x["subject_id"])):x["marks"] for x in mark_rows}
        subject_means=[]
        for sub in subjects:
            vals=[]
            for st in students:
                value=marks.get((int(st["id"]),int(sub["id"])))
                if value is not None:
                    try:
                        vals.append(float(value))
                    except (TypeError,ValueError):
                        pass
            subject_means.append((sub, sum(vals)/len(vals) if vals else None, len(vals)))
        computed=[]
        for st in students:
            total=0.0; points=0.0; count=0; vals=[]
            for sub in subjects:
                value=marks.get((int(st["id"]),int(sub["id"])))
                if value is None:
                    vals.extend(["—","—","—"])
                else:
                    try:
                        grade,pts=_subject_grade_points(cur,sid,int(sub["id"]),value)
                    except Exception as exc:
                        print("DAVISCHOOL MARKSHEET PDF GRADE FALLBACK:", repr(exc), flush=True)
                        grade,pts=_default_grade_points(float(value or 0))
                    total+=float(value or 0); points+=float(pts or 0); count+=1
                    vals.extend([f"{float(value):.1f}",str(grade),f"{float(pts):.1f}"])
            average=(total/count) if count else 0.0
            computed.append((st,total,points,count,vals,_overall_grade(cur,sid,average) if count else "—"))
        computed.sort(key=lambda x:x[1],reverse=True)
        school=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
        con.close()
        styles=_pdf_styles()
        pdf_class_title = (f"{combined_grade} — ALL STREAMS" if combined_mode else f"{cr['name'] if cr else 'Class'} {cr['stream'] if cr and cr['stream'] else ''}")
        story=_pdf_school_header(school,styles,"Class Marksheet",f"{pdf_class_title} · {er['name'] if er else 'Examination'} · {term or 'Term'} {year or ''}")
        header1=["Adm No.","Student"]; header2=["",""]
        if combined_mode:
            header1.append("Stream"); header2.append("")
        for sub in subjects:
            header1.extend([str(sub["name"]),"",""]); header2.extend(["MKS","GRD","PTS"])
        header1.extend(["OVERALL","","","","",""]); header2.extend(["MKS","PTS","AVG %","GRD","POS"])
        data=[header1,header2]
        last_total=None; pos=0
        for idx,(st,total,points,count,vals,overall_grade) in enumerate(computed,1):
            if last_total is None or total!=last_total: pos=idx; last_total=total
            avg=(total/count) if count else 0
            prefix=[str(st["admission_no"] or ""),str(st["name"] or "")]
            if combined_mode:
                student_stream = str(st["stream"] or "").strip() or class_stream_by_id.get(int(st["class_id"] or 0), "")
                prefix.append(student_stream)
            data.append(prefix+vals+[f"{total:.1f}",f"{points:.1f}",f"{avg:.1f}",str(overall_grade),str(pos)])
        if len(data)==2:
            data.append(["","No students or marks found."]+[""]*(len(header1)-2))
        subject_width_count = len(header1) - (8 if combined_mode else 7)
        col_widths=[22*mm,42*mm] + ([18*mm] if combined_mode else []) + [15*mm]*subject_width_count + [16*mm]*5
        table=Table(data,colWidths=col_widths,repeatRows=2)
        table.setStyle(TableStyle([
            ("GRID",(0,0),(-1,-1),0.35,colors.black),("BACKGROUND",(0,0),(-1,1),colors.HexColor("#eef2f7")),
            ("FONTNAME",(0,0),(-1,1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),6),
            ("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("ALIGN",(1,2),(1,-1),"LEFT"),("FONTSIZE",(1,2),(1,-1),7)
        ]))
        story += [table, Spacer(1,6), Paragraph("Subject Means",styles["normal"])]
        pdf_subject_sorted = sorted(
            [x for x in subject_means if x[1] is not None],
            key=lambda x: (-float(x[1]), str(x[0]["name"]).lower())
        )
        pdf_subject_positions = {}
        pdf_last_mean = None
        pdf_last_position = 0
        for idx, item in enumerate(pdf_subject_sorted, 1):
            mean_value = float(item[1])
            if pdf_last_mean is None or mean_value != pdf_last_mean:
                pdf_last_position = idx
                pdf_last_mean = mean_value
            pdf_subject_positions[int(item[0]["id"])] = pdf_last_position
        mean_data=[["Subject","Mean","Entries","Position"]]+[
            [str(sub["name"]),f"{mean:.2f}" if mean is not None else "—",str(count),str(pdf_subject_positions.get(int(sub["id"]),"—"))]
            for sub,mean,count in subject_means
        ]
        if len(mean_data)==1: mean_data.append(["No subject marks available.","","",""])
        mean_table=Table(mean_data,colWidths=[85*mm,30*mm,30*mm,30*mm],repeatRows=1)
        mean_table.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.35,colors.black),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eef2f7")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),("ALIGN",(1,1),(-1,-1),"CENTER")]))
        story += [mean_table, Spacer(1,4), Paragraph("Generated by DaviSchool Management System.",styles["small"])]
        pdf=_pdf_build(story,landscape(A3),"Class Marksheet")
        filename=f"marksheet_{(combined_grade if combined_mode else (cr['name'] if cr else 'class'))}_{(er['name'] if er else 'exam')}.pdf"
        return _pdf_response(pdf,filename)


    except Exception as exc:
        return _pdf_route_error(request, "class_marksheets_pdf", exc)

@router.get("/app/academics/class-analysis/pdf")
def class_analysis_pdf(request: Request, exam_id: str = "", class_id: str = ""):

    try:
        sid=_school_session(request)
        if not sid:return RedirectResponse("/")
        if not _require_permission(request,sid,"reports.view"):
            return HTMLResponse("You do not have permission to download class analysis.",403)
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.units import mm
        con=_db();cur=con.cursor()
        exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        classes=cur.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name,stream",(sid,)).fetchall()
        eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
        cid=int(class_id) if class_id.isdigit() else 0
        er=cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?",(eid,sid)).fetchone() if eid else None
        cr=cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?",(cid,sid)).fetchone() if cid else None
        stats=[]; ranking=[]
        if eid and cid:
            stats=cur.execute("""SELECT sub.name subject,COUNT(m.id) entries,COALESCE(AVG(m.marks),0) average,COALESCE(MAX(m.marks),0) highest,COALESCE(MIN(m.marks),0) lowest
              FROM subjects sub LEFT JOIN marks m ON m.subject_id=sub.id AND m.exam_id=? AND m.school_id=? AND m.class_id=?
              WHERE sub.school_id=? GROUP BY sub.id,sub.name ORDER BY sub.name""",(eid,sid,cid,sid)).fetchall()
            students=cur.execute("SELECT id,name,admission_no FROM students WHERE school_id=? AND class_id=? ORDER BY name",(sid,cid)).fetchall()
            for st in students: ranking.append((st,_student_result(cur,sid,int(st["id"]),eid)))
            ranking.sort(key=lambda x:(-float(x[1]["total"]),str(x[0]["name"])))
        school=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone();con.close()
        styles=_pdf_styles()
        story=_pdf_school_header(school,styles,"Class Analysis",f"{cr['name'] if cr else 'Class'} {cr['stream'] if cr and cr['stream'] else ''} · {er['name'] if er else 'Examination'}")
        story.append(Paragraph("Subject Performance",styles["normal"]))
        data=[["Subject","Entries","Average","Highest","Lowest"]]+[[str(x["subject"]),str(x["entries"]),f"{float(x['average'] or 0):.2f}",f"{float(x['highest'] or 0):.1f}",f"{float(x['lowest'] or 0):.1f}"] for x in stats]
        if len(data)==1:data.append(["No subject results found.","","","",""])
        t=Table(data,colWidths=[70*mm,25*mm,30*mm,30*mm,30*mm],repeatRows=1);t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.black),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eef2f7")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8)]));story += [t,Spacer(1,8),Paragraph("Learner Ranking",styles["normal"])]
        data=[["Position","Admission","Student","Total","Average","Grade"]]+[[str(i),str(st["admission_no"] or ""),str(st["name"]),f"{res['total']:.1f}",f"{res['average']:.1f}%",str(res["overall_grade"])] for i,(st,res) in enumerate(ranking,1)]
        if len(data)==1:data.append(["","","No learner results found.","","",""])
        t=Table(data,colWidths=[20*mm,30*mm,65*mm,25*mm,30*mm,25*mm],repeatRows=1);t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.black),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eef2f7")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8)]));story.append(t)
        return _pdf_response(_pdf_build(story,landscape(A4),"Class Analysis"),f"class_analysis_{cr['name'] if cr else 'class'}.pdf")


    except Exception as exc:
        return _pdf_route_error(request, "class_analysis_pdf", exc)

@router.get("/app/academics/student-analysis/pdf")
def student_analysis_pdf(request: Request, exam_id: str = "", student_id: str = ""):

    try:
        sid=_school_session(request)
        if not sid:return RedirectResponse("/")
        if not _require_permission(request,sid,"reports.view"):
            return HTMLResponse("You do not have permission to download student analysis.",403)
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.units import mm
        con=_db();cur=con.cursor()
        exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        students=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.name",(sid,)).fetchall()
        eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
        stid=int(student_id) if student_id.isdigit() else (int(students[0]["id"]) if students else 0)
        st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(stid,sid)).fetchone()
        result=_student_result(cur,sid,stid,eid) if st and eid else {"details":[],"total":0.0,"points":0.0,"average":0.0,"overall_grade":"—"}
        er=cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?",(eid,sid)).fetchone() if eid else None
        school=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone();con.close()
        styles=_pdf_styles(); story=_pdf_school_header(school,styles,"Student Analysis",f"{st['name'] if st else 'Student'} · {er['name'] if er else 'Examination'}")
        if st: story += [Paragraph(f"Admission: {escape(str(st['admission_no'] or ''))} · Class: {escape(str(st['class_name'] or ''))} {escape(str(st['stream'] or ''))}",styles["normal"]),Spacer(1,5)]
        story += [Paragraph(f"Total: {result['total']:.1f}    Average: {result['average']:.1f}%    Overall Grade: {escape(str(result['overall_grade']))}",styles["normal"]),Spacer(1,6)]
        data=[["Subject","Mark","Grade","Points"]]+[[str(r["name"]),f"{mark:.1f}",str(grade),f"{points:.1f}"] for r,mark,grade,points in result["details"]]
        if len(data)==1:data.append(["No marks recorded.","","",""])
        t=Table(data,colWidths=[85*mm,30*mm,30*mm,30*mm],repeatRows=1);t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.black),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eef2f7")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9)]));story.append(t)
        return _pdf_response(_pdf_build(story,A4,"Student Analysis"),f"student_analysis_{st['name'] if st else 'student'}.pdf")


    except Exception as exc:
        return _pdf_route_error(request, "student_analysis_pdf", exc)

@router.get("/app/report-cards/class-pdf")
def report_cards_class_pdf(request: Request, exam_id: str = "", class_id: str = "", inline: str = ""):
    try:
        sid=_school_session(request)
        if not sid:return RedirectResponse("/")
        if not _require_permission(request,sid,"reports.view"):
            return HTMLResponse("You do not have permission to download report cards.",403)
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib.units import mm
        con=_db();cur=con.cursor();_ensure_report_card_fields(cur)
        eid=int(exam_id) if exam_id.isdigit() else 0
        cid=int(class_id) if class_id.isdigit() else 0
        if not eid or not cid:
            con.close();return HTMLResponse("Please select an examination and class.",400)
        er=cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?",(eid,sid)).fetchone()
        cr=cur.execute("SELECT * FROM classes WHERE id=? AND school_id=?",(cid,sid)).fetchone()
        if not er or not cr:
            con.close();return HTMLResponse("Examination or class not found.",404)
        students=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? AND s.class_id=? ORDER BY s.name,s.id",(sid,cid)).fetchall()
        if not students:
            con.close();return HTMLResponse("No students found in the selected class.",404)
        school=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
        styles=_pdf_styles();story=[];_ensure_academic_locks_table(cur)
        grading_rules=_load_grading_rules(cur,sid)
        for student_index,st in enumerate(students):
            result=_student_result(cur,sid,int(st["id"]),eid)
            rows=cur.execute("""SELECT sub.id subject_id,sub.name,m.marks FROM marks m JOIN subjects sub ON sub.id=m.subject_id
                WHERE m.school_id=? AND m.student_id=? AND m.exam_id=? ORDER BY sub.name""",(sid,st["id"],eid)).fetchall()
            marked=[r["subject_id"] for r in rows if r["marks"] is not None and str(r["marks"])!=""]
            locked=cur.execute("SELECT COUNT(*) c FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id IN (%s)"%(",".join("?" for _ in marked)),[sid,eid,cid]+marked).fetchone()["c"] if marked else 0
            status="FINAL" if marked and int(locked)==len(marked) else "DRAFT"
            totals=cur.execute("""SELECT s.id,COALESCE(SUM(m.marks),0) total FROM students s LEFT JOIN marks m ON m.student_id=s.id AND m.school_id=? AND m.exam_id=? WHERE s.school_id=? AND s.class_id=? GROUP BY s.id ORDER BY total DESC,s.id""",(sid,eid,sid,cid)).fetchall()
            position="—";last_total=None;pos=0
            for idx,t in enumerate(totals,1):
                tv=float(t["total"] or 0)
                if last_total is None or tv!=last_total:pos=idx;last_total=tv
                if int(t["id"])==int(st["id"]):position=pos;break
            comments={}
            for r in rows:
                x=cur.execute("SELECT comment FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=? LIMIT 1",(sid,st["id"],eid,r["subject_id"])).fetchone()
                value=(x["comment"] if x else "") or ""
                if not value and r["marks"] is not None:
                    try:_,_,value=_subject_grade_details(cur,sid,int(r["subject_id"]),r["marks"],grading_rules)
                    except Exception:pass
                comments[int(r["subject_id"])]=value
            tc=cur.execute("SELECT comment FROM class_teacher_comments WHERE school_id=? AND student_id=? AND exam_id=? LIMIT 1",(sid,st["id"],eid)).fetchone()
            rc=cur.execute("SELECT comment FROM report_comments WHERE school_id=? AND student_id=? AND exam_id=? ORDER BY id DESC LIMIT 1",(sid,st["id"],eid)).fetchone()
            rs=cur.execute("SELECT opening_date,closing_date FROM report_card_settings WHERE school_id=? AND exam_id=? LIMIT 1",(sid,eid)).fetchone()
            story += _pdf_school_header(school,styles,"Student Report Card","%s · Admission %s · %s"%(st["name"],st["admission_no"] or "",er["name"]))
            story += [Paragraph("Class: %s %s · Status: %s"%(st["class_name"] or "",st["stream"] or "",status),styles["normal"]),Spacer(1,5)]
            data=[["Subject","Mark","Grade","Points","Performance Comment"]]
            for r,mark,grade,points in result["details"]:
                data.append([str(r["name"]),"%0.1f"%mark,str(grade),"%0.1f"%points,str(comments.get(int(r["subject_id"]),""))])
            if len(data)==1:data.append(["No marks recorded.","","","",""])
            t=Table(data,colWidths=[35*mm,18*mm,20*mm,20*mm,80*mm],repeatRows=1)
            t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.black),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eef2f7")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP")]))
            story += [t,Spacer(1,7),Paragraph("Subjects: %d · Total: %.1f · Average: %.1f%% · Points: %.1f · Overall Grade: %s · Position: %s / %d"%(result["count"],result["total"],result["average"],result["points"],result["overall_grade"],position,len(totals)),styles["normal"])]
            if tc:story += [Spacer(1,6),Paragraph("Class Teacher's Comment: "+escape(str(tc["comment"] or "")),styles["normal"])]
            if rc:story += [Spacer(1,4),Paragraph("Additional Report Comment: "+escape(str(rc["comment"] or "")),styles["normal"])]
            if rs:story += [Spacer(1,4),Paragraph("Date of Opening: %s    Date of Closing: %s"%(rs["opening_date"] or "",rs["closing_date"] or ""),styles["normal"])]
            if student_index<len(students)-1:story.append(PageBreak())
        con.close()
        pdf=_pdf_build(story,A4,"Class Report Cards - %s"%cr["name"])
        if inline:return Response(content=pdf,media_type="application/pdf",headers={"Content-Disposition":"inline; filename=\"report_cards_%s.pdf\""%cr["name"]})
        return _pdf_response(pdf,"report_cards_%s.pdf"%cr["name"])
    except Exception as exc:
        return _pdf_route_error(request,"report_cards_class_pdf",exc)

@router.get("/app/report-cards/pdf")
def report_card_pdf(request: Request, exam_id: str = "", student_id: str = ""):

    try:
        sid=_school_session(request)
        if not sid:return RedirectResponse("/")
        if not _require_permission(request,sid,"reports.view"):
            return HTMLResponse("You do not have permission to download report cards.",403)
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.units import mm
        con=_db();cur=con.cursor();_ensure_report_card_fields(cur)
        exams=cur.execute("SELECT * FROM exams WHERE school_id=? ORDER BY id DESC",(sid,)).fetchall()
        students=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.school_id=? ORDER BY s.name",(sid,)).fetchall()
        eid=int(exam_id) if exam_id.isdigit() else (int(exams[0]["id"]) if exams else 0)
        stid=int(student_id) if student_id.isdigit() else (int(students[0]["id"]) if students else 0)
        st=cur.execute("SELECT s.*,c.name class_name,c.stream FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.school_id=?",(stid,sid)).fetchone()
        if not st:
            con.close();return HTMLResponse("Student not found.",404)
        result=_student_result(cur,sid,stid,eid)
        rows=cur.execute("""SELECT sub.id subject_id,sub.name,m.marks FROM marks m JOIN subjects sub ON sub.id=m.subject_id
            WHERE m.school_id=? AND m.student_id=? AND m.exam_id=? ORDER BY sub.name""",(sid,stid,eid)).fetchall()
        _ensure_academic_locks_table(cur)
        marked=[r["subject_id"] for r in rows if r["marks"] is not None and str(r["marks"])!=""]
        locked=cur.execute("SELECT COUNT(*) c FROM academic_locks WHERE school_id=? AND exam_id=? AND class_id=? AND subject_id IN (%s)"%(",".join("?" for _ in marked)),[sid,eid,st["class_id"]]+marked).fetchone()["c"] if marked else 0
        report_final=(int(locked)==len(marked)) if marked else False
        totals=cur.execute("""SELECT s.id,COALESCE(SUM(m.marks),0) total FROM students s LEFT JOIN marks m ON m.student_id=s.id AND m.school_id=? AND m.exam_id=? WHERE s.school_id=? AND s.class_id=? GROUP BY s.id ORDER BY total DESC,s.id""",(sid,eid,sid,st["class_id"])).fetchall()
        position="—"; last_total=None; pos=0
        for idx,t in enumerate(totals,1):
            tv=float(t["total"] or 0)
            if last_total is None or tv!=last_total:pos=idx;last_total=tv
            if int(t["id"])==stid:position=pos;break
        comments={}
        try:
            pdf_grading_rules=_load_grading_rules(cur,sid)
        except Exception:
            pdf_grading_rules={}
        for r in rows:
            x=cur.execute("SELECT comment FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=? LIMIT 1",(sid,stid,eid,r["subject_id"])).fetchone()
            value=(x["comment"] if x else "") or ""
            if not value and r["marks"] is not None:
                try:
                    _,_,value=_subject_grade_details(cur,sid,int(r["subject_id"]),r["marks"],pdf_grading_rules)
                except Exception:
                    pass
            comments[int(r["subject_id"])]=value
        tc=cur.execute("SELECT comment FROM class_teacher_comments WHERE school_id=? AND student_id=? AND exam_id=? LIMIT 1",(sid,stid,eid)).fetchone()
        rc=cur.execute("SELECT comment FROM report_comments WHERE school_id=? AND student_id=? AND exam_id=? ORDER BY id DESC LIMIT 1",(sid,stid,eid)).fetchone()
        rs=cur.execute("SELECT opening_date,closing_date FROM report_card_settings WHERE school_id=? AND exam_id=? LIMIT 1",(sid,eid)).fetchone()
        er=cur.execute("SELECT * FROM exams WHERE id=? AND school_id=?",(eid,sid)).fetchone() if eid else None
        school=cur.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone();con.close()
        styles=_pdf_styles(); subtitle=f"{st['name']} · Admission {st['admission_no'] or ''} · {er['name'] if er else 'Examination'}"
        story=_pdf_school_header(school,styles,"Student Report Card",subtitle)
        status="FINAL" if report_final else "DRAFT"
        story += [Paragraph(f"Class: {st['class_name'] or ''} {st['stream'] or ''} · Status: {status}",styles["normal"]),Spacer(1,5)]
        data=[["Subject","Mark","Grade","Points","Performance Comment"]]
        for r,mark,grade,points in result["details"]:
            data.append([str(r["name"]),f"{mark:.1f}",str(grade),f"{points:.1f}",str(comments.get(int(r["subject_id"]),""))])
        if len(data)==1:data.append(["No marks recorded.","","","",""])
        t=Table(data,colWidths=[35*mm,18*mm,20*mm,20*mm,80*mm],repeatRows=1);t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.black),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eef2f7")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP")]))
        story += [t,Spacer(1,7),Paragraph(f"Subjects: {result['count']} · Total: {result['total']:.1f} · Average: {result['average']:.1f}% · Points: {result['points']:.1f} · Overall Grade: {result['overall_grade']} · Position: {position} / {len(totals)}",styles["normal"])]
        if tc: story += [Spacer(1,6),Paragraph("Class Teacher's Comment: "+escape(str(tc["comment"] or "")),styles["normal"])]
        if rc: story += [Spacer(1,4),Paragraph("Additional Report Comment: "+escape(str(rc["comment"] or "")),styles["normal"])]
        if rs: story += [Spacer(1,4),Paragraph(f"Date of Opening: {rs['opening_date'] or ''}    Date of Closing: {rs['closing_date'] or ''}",styles["normal"])]
        pdf=_pdf_build(story,A4,"Student Report Card")
        return _pdf_response(pdf,f"report_card_{st['name']}.pdf")

    except Exception as exc:
        return _pdf_route_error(request, "report_card_pdf", exc)