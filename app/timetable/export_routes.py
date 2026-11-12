"""Printable PDF and Excel timetable exports."""
from __future__ import annotations

from io import BytesIO
from datetime import datetime
from html import escape
import logging
import re
import base64
from xml.sax.saxutils import escape as xml_escape

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from app.timetable.views import get_timetable_view
from app.timetable.setup import TimetableSetupError
from app.timetable.export_grid import build_export_grid
from app.timetable.time_utils import EAT

logger = logging.getLogger(__name__)


def register_timetable_export_routes(app, get_db, get_school_obj):
    def school_for(request):
        if not request.session.get("email") or request.session.get("role") not in ("school_admin", "registrar", "super_admin"):
            return None
        return get_school_obj(request)

    def load_view(request, profile_id, view_type, class_id, teacher_id, room_id):
        school = school_for(request)
        if not school:
            return None, None, RedirectResponse("/", 303)
        target_id = {"class":class_id,"teacher":teacher_id,"room":room_id}.get(view_type,0)
        con = get_db()
        try:
            result = get_timetable_view(con, int(school["id"]), int(profile_id), view_type, int(target_id))
            return school, result, None
        except TimetableSetupError as exc:
            return school, None, HTMLResponse(str(exc), status_code=400)
        finally:
            con.close()

    def field_value(row, key, default=None):
        try:
            value = row[key]
            return default if value is None else value
        except (KeyError, IndexError, TypeError):
            return default

    def filename_prefix(school, result):
        raw = str(school["name"] or "School") + "-" + str(result["title"] or "Timetable")
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")
        return (safe or "Mabale_ICT-Timetable")[:90]

    def allocated_room_name(lesson):
        """Return a room label only for a real, explicitly allocated room."""
        room_id = lesson.get("room_id")
        room_name = str(lesson.get("room_name") or "").strip()
        if not room_id or not room_name or room_name.casefold() in {
            "room not assigned", "not assigned", "unassigned", "—", "-"
        }:
            return ""
        return room_name

    def school_logo_data(school):
        value = str(field_value(school, "logo_data", "") or "").strip()
        if not value:
            return ""
        return value if value.startswith("data:image/") else "data:image/png;base64," + value

    def school_details(school):
        fields = [("Phone", field_value(school, "phone", "")),
                  ("Email", field_value(school, "email", ""))]
        return [(label, str(value).strip()) for label, value in fields if str(value or "").strip()]

    def status_label(profile):
        status = str(field_value(profile, "status", "draft") or "draft").strip().lower()
        return {"draft":"Draft", "published":"Published", "pending_approval":"Pending Approval",
                "pending approval":"Pending Approval", "archived":"Archived"}.get(status, status.replace("_", " ").title())

    def teacher_color_hex(value):
        color = str(value or "").strip()
        return color.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", color) else "#2563EB"

    def teacher_tint_hex(value, ratio=0.17):
        color = teacher_color_hex(value)[1:]
        channels = [int(color[index:index+2], 16) for index in (0, 2, 4)]
        return "".join(f"{round(channel * (1-ratio) + 255 * ratio):02X}" for channel in channels)

    def cell_map(result):
        periods = result["periods"]
        index = {int(p["id"]):i for i,p in enumerate(periods)}
        starts = {}
        continued = {}
        for lesson in result["lessons"]:
            key = (int(lesson["day_id"]),int(lesson["period_id"]))
            starts.setdefault(key,[]).append(lesson)
            start = index.get(int(lesson["period_id"]))
            if start is not None:
                for offset in range(1,int(lesson["duration_periods"] or 1)):
                    if start + offset < len(periods):
                        continued[(int(lesson["day_id"]),int(periods[start+offset]["id"]))] = lesson
        return starts, continued

    @app.get("/app/timetable/export/print", response_class=HTMLResponse)
    def timetable_export_print(request: Request, profile_id: int, view_type: str = "school",
        class_id: int = 0, teacher_id: int = 0, room_id: int = 0, remedial_display: str = "combined"):
        school, result, error = load_view(request, profile_id, view_type, class_id, teacher_id, room_id)
        if error:
            return error
        layout = build_export_grid(result, view_type)
        timeline = layout["timeline"]
        headers = ["Day"] + (["Class / Stream"] if layout["show_class_column"] else [])
        headers += [(str(item["start_time"]) + "–" + str(item["end_time"])) if kind == "break" else (str(item["label"]) + "<br>" + str(item["start_time"]) + "–" + str(item["end_time"])) for _,kind,item in timeline]
        body_rows = []
        for row in layout["rows"]:
            cells = []
            if row["day_first"]:
                cells.append(f"<th rowspan='{row['day_rowspan']}' class='day'>{escape(str(row['day'].get('day_code') or row['day']['day_name']))}</th>")
            if layout["show_class_column"]:
                cl=row["class"]
                cells.append("<th class='class'>" + escape(cl["class_name"] + ((" " + cl["stream"]) if cl["stream"] else "")) + "</th>")
            for cell in row["cells"]:
                if cell["kind"] == "break_placeholder":
                    continue
                if cell["kind"] == "break":
                    b=cell["item"]
                    cells.append(f"<td class='break' rowspan='{cell['rowspan']}'><span>{''.join('<i>' + ('&nbsp;' if ch.isspace() else escape(ch)) + '</i>' for ch in str(b['label']))}</span></td>")
                elif cell["kind"] == "free":
                    cells.append("<td class='free'></td>")
                elif cell["kind"] == "continued":
                    labels=[]
                    for lesson in cell["lessons"]:
                        labels.append("↳ " + escape(str(lesson.get("subject_initial") or "").strip().upper() or "—") + " continues")
                    cells.append("<td class='continued'>" + "<br>".join(labels) + "</td>")
                else:
                    cards=[]
                    for lesson in cell["lessons"]:
                        subject_initial = escape(str(lesson.get("subject_initial") or "").strip().upper() or "—")
                        teacher_initials = str(lesson.get("teacher_initials") or "").strip().upper()
                        if not teacher_initials:
                            name_parts = [part for part in str(lesson.get("teacher_name") or "").split() if part]
                            teacher_initials = "".join(part[0] for part in (name_parts[:1] + (name_parts[-1:] if len(name_parts) > 1 else []))).upper()[:4] or "—"
                        allocated_room = allocated_room_name(lesson)
                        room_detail = "" if layout["room_view"] or not allocated_room else "<small class='room-detail'>⌂ " + escape(allocated_room) + "</small>"
                        card_color = str(lesson.get("teacher_color") or "").strip()
                        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", card_color):
                            card_color = "#2563EB"
                        class_label = str(lesson.get("class_name") or "").strip()
                        stream_label = str(lesson.get("stream") or "").strip()
                        class_full = class_label + ((" " + stream_label) if stream_label else "")
                        class_initials = escape(str(lesson.get("class_initials") or "").strip().upper() or class_full or "—")
                        if view_type in ("teacher", "room"):
                            footer_detail = (
                                ("<span class='resource-room'>" + escape(str(lesson.get("room_name"))) + "</span>" if view_type == "teacher" and lesson.get("room_name") else "") +
                                ("<span class='resource-teacher'>" + escape(teacher_initials) + "</span>" if view_type == "room" else "")
                            )
                            detail = (
                                "<small class='resource-subject'>" + subject_initial + "</small>"
                                "<b class='resource-class'>" + class_initials + "</b>"
                                "<span class='resource-footer'>" + footer_detail + "</span>"
                                "<span class='resource-duration'>" + str(max(1, int(lesson.get("duration_periods") or 1))) + "P</span>"
                            )
                            cards.append("<div class='lesson resource-lesson' style='--teacher-color:" + card_color + "' title='" + escape(class_full) + "'>" + detail + "</div>")
                        else:
                            footer_detail = "<span class='teacher-initials'>" + escape(teacher_initials) + "</span>"
                            detail = (
                                "<span class='duration-label'>" + str(max(1, int(lesson.get("duration_periods") or 1))) + "P</span>"
                                "<b class='subject-initials'>" + subject_initial + "</b>"
                                + room_detail + footer_detail
                            )
                            cards.append("<div class='lesson' style='--teacher-color:" + card_color + "'>" + detail + "</div>")
                    cells.append(f"<td class='slot' colspan='{cell['span']}'>" + "".join(cards) + "</td>")
            row_height = " style='height:" + str(round(100 / max(1, len(layout["rows"])), 4)) + "%'" if view_type in ("class", "teacher", "room") else ""
            body_rows.append("<tr" + row_height + ">" + "".join(cells) + "</tr>")
        def print_session_table(items, include_rotation=False):
            if not items:
                return "<p class='empty'>No sessions scheduled in this section.</p>"
            labels = (["Weekend rotation"] if include_rotation else []) + ["Date / Day", "Time", "Lesson / Activity", "Class / Group", "Teacher(s)", "Venue"]
            rows = []
            for item in items:
                date_label = str(item.get("session_date") or item.get("day_name") or "Weekly")
                if item.get("session_date") and item.get("day_name"):
                    date_label += " · " + str(item["day_name"])
                values = ([str(item.get("rotation_label") or "Weekend rotation")] if include_rotation else []) + [
                    date_label, str(item["start_time"]) + "–" + str(item["end_time"]),
                    str(item.get("subject_name") or item.get("programme_name") or item.get("session_type") or "Session"),
                    str(item.get("class_names") or "—"), str(item.get("teacher_names") or "—"),
                    str(item.get("room_name") or "—"),
                ]
                rows.append("<tr>" + "".join("<td>" + escape(value) + "</td>" for value in values) + "</tr>")
            return "<table class='session-table'><thead><tr>" + "".join("<th>" + escape(label) + "</th>" for label in labels) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"

        dated_html = ""
        if result.get("dated_instructional_sessions"):
            dated_html = "<section class='extra-section'><h3>Calendar-dated instructional lessons</h3>" + print_session_table(result["dated_instructional_sessions"]) + "</section>"
        weekday_html = ""
        if result.get("weekday_remedials"):
            remedial_class = " extra-remedial-separate" if remedial_display == "separate" else ""
            weekday_html = "<section class='extra-section" + remedial_class + "'><h3>Weekday remedial &amp; study sessions</h3>" + print_session_table(result["weekday_remedials"]) + "</section>"
        weekend_html = ""
        if result.get("weekend_sessions"):
            weekend_html = "<section class='extra-section extra-weekend'><h3>Weekend lessons &amp; remedials</h3>" + print_session_table(result["weekend_sessions"], True) + "</section>"

        school_name=escape(str(field_value(school,"name","School")))
        title=escape("MASTER TIMETABLE" if view_type == "school" else ("TEACHER " + str(result["target"]["name"]) if view_type == "teacher" else str(result["title"])))
        logo_src=school_logo_data(school)
        logo_img=("<img style='width:60px;height:60px;object-fit:contain' src='" + escape(logo_src, quote=True) + "' alt='School logo'>") if logo_src else ""
        school_details_html=" · ".join(escape(label + ": " + value) for label,value in school_details(school))
        timetable_fields = [
            ("Term", str(result["profile"]["term"])),
            ("Year", str(result["profile"]["academic_year"])),
            ("Status", status_label(result["profile"])),
        ]
        meta_html = "".join("<span style='display:inline-block;margin:0 22px'>" + escape(label) + ": <b>" + escape(value) + "</b></span>" for label,value in timetable_fields)
        header_html = "<th>" + headers[0] + "</th>" + (("<th>" + headers[1] + "</th>") if layout["show_class_column"] else "") + "".join("<th class='" + ("break-header" if kind == "break" else "period-header") + "'>" + (str(item["start_time"]) + "–" + str(item["end_time"]) if kind == "break" else str(item["label"]) + "<br>" + str(item["start_time"]) + "–" + str(item["end_time"])) + "</th>" for _, kind, item in timeline)
        specialized_export = view_type != "school"
        timetable_table_class = "specialized-timetable" if specialized_export else "main-timetable"
        generated_at = datetime.now(EAT).strftime("%d %b %Y %H:%M EAT")
        export_footer = ("<footer class='export-footer'><span>Mabale_ICT Management System · Generated: " + escape(generated_at) + "</span><span>Total scheduled lessons: " + str(len(result["lessons"])) + "</span></footer>") if view_type in ("teacher", "room") else ""
        room_period_css = ".resource-duration{top:3px;bottom:auto;right:5px}" if view_type == "room" else ""
        html=f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
        <style>{room_period_css}
        @page{{size:A4 landscape;margin:7mm}}*{{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}}body{{font:10px Arial,sans-serif;color:#234638;margin:12px}}
        h1,h2,p{{text-align:center;margin:3px}}h1{{font-size:17px}}h2{{font-size:13px}}p{{color:#647b6a;margin-bottom:12px}}
        table{{width:100%;border-collapse:collapse;table-layout:fixed;min-width:900px}}th,td{{border:1px solid #c7d9ca;padding:4px;text-align:center;vertical-align:middle;overflow-wrap:anywhere}}
        thead th{{background:#347b50;color:white;font-size:9px;padding:7px 3px}}th.day{{background:#edf5ee;color:#315b3e;width:38px;text-align:center;vertical-align:middle}}th.class{{background:#f5f9f5;color:#315b3e;width:48px}}
        table.specialized-timetable{{width:auto;min-width:0}}table.specialized-timetable{{width:max-content;max-width:100%;table-layout:auto}}table.specialized-timetable th.period-header,table.specialized-timetable td.slot{{width:28px;min-width:28px}}table.specialized-timetable th.break-header,table.specialized-timetable td.break{{width:12px;min-width:12px;max-width:12px}}table.specialized-timetable td.break>span{{font-size:11px}}body.individual-sheet table.specialized-timetable{{width:100%;max-width:100%;table-layout:fixed}}body.individual-sheet table.specialized-timetable th.period-header,body.individual-sheet table.specialized-timetable td.slot{{width:auto;min-width:0}}body.individual-sheet table.specialized-timetable th.break-header,body.individual-sheet table.specialized-timetable td.break{{width:auto;min-width:0;max-width:none}}body.individual-sheet table.specialized-timetable{{height:100%;border-collapse:collapse}}
        body.individual-sheet table.specialized-timetable tbody tr{{height:1px}}
        body.individual-sheet table.specialized-timetable td.slot{{display:flex;align-items:stretch;padding:0;vertical-align:stretch}}
        body.individual-sheet .lesson{{position:relative;box-sizing:border-box;flex:1 1 0;width:100%;height:100%;min-height:0;margin:0;border-radius:0;padding:13px 5px 5px}}
        body.individual-sheet .lesson+.lesson{{border-left-width:3px}}
        body.individual-sheet table.specialized-timetable td.slot{{height:100%}}
        td.slot{{background:#fff}}.resource-lesson{{position:relative;min-height:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:12px 4px 14px;border-radius:0;background:color-mix(in srgb,var(--teacher-color) 12%,white);border:1px solid color-mix(in srgb,var(--teacher-color) 42%,white);border-left:3px solid var(--teacher-color);margin:0}}.resource-subject{{position:absolute;top:4px;left:5px;right:auto;font-size:10px;line-height:1;font-weight:900;color:#365b40;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;writing-mode:horizontal-tb;z-index:2}}.resource-class{{display:flex;flex:1;align-items:center;justify-content:center;width:100%;min-height:0;text-align:center;font-size:clamp(25px,2.2vw,34px);line-height:.95;font-weight:950;letter-spacing:-.04em;color:#263f30;overflow-wrap:anywhere}}.resource-duration{{position:absolute;bottom:3px;right:5px;left:auto;font-size:9px;line-height:1;font-weight:900;color:#536b58;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;writing-mode:horizontal-tb;z-index:2}}.resource-footer{{position:absolute;bottom:3px;left:4px;right:30px;display:flex;justify-content:space-between;font-size:7px;color:#637968}}.resource-teacher{{margin-left:auto;font-weight:800;color:#245b39}}.lesson{{position:relative;min-height:66px;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;background:color-mix(in srgb,var(--teacher-color) 17%,white);border:1px solid color-mix(in srgb,var(--teacher-color) 48%,white);border-left:4px solid var(--teacher-color);border-radius:6px;padding:13px 5px 5px;margin:2px;font-size:9px;line-height:1.2}}
        .lesson .duration-label{{position:absolute;top:3px;right:5px;font-size:8px;font-weight:bold;background:#d5e9d9;border-radius:8px;padding:2px 4px}}.lesson .subject-initials{{display:block;text-align:center;font-size:12px;font-weight:900;letter-spacing:.4px}}.lesson .room-detail{{display:block;color:#55705d;font-size:8px;margin-top:4px;max-width:100%;overflow-wrap:anywhere}}.lesson .teacher-initials,.lesson .class-detail{{align-self:flex-end;margin-top:auto;background:#245b39;color:#fff;border-radius:4px;padding:2px 5px;font-size:8px;font-weight:900}}.lesson .class-detail{{max-width:100%;text-align:right;overflow-wrap:anywhere}}th.break-header{{width:90%}}td.break{{width:90%;background:#f1ead8;color:#75551d;vertical-align:middle;text-align:center;min-width:24px;padding:0;position:relative}}td.break>span{{display:flex;flex-direction:column;justify-content:center;align-items:center;min-height:100%;height:100%;font-size:18px;font-weight:950;line-height:1}}td.break>span i{{display:block;font-style:normal;line-height:1}}td.free{{background:#fbfdfb}}td.continued{{background:#f6faf6;color:#7b9480;font-size:8px}}
        .actions{{text-align:center;margin-bottom:10px}}button{{padding:8px 15px;background:#17633b;color:#fff;border:0;border-radius:7px}}.export-footer{{display:flex;justify-content:space-between;gap:12px;position:fixed;bottom:0;left:0;right:0;padding:5px 12px;font-size:8px;color:#536b58;border-top:1px solid #c7d9ca;background:#fff}}body.individual-sheet{{padding-bottom:24px}}
        .extra-section{{margin-top:18px;break-inside:avoid}}.extra-section h3{{font-size:12px;color:#1d563b;margin:0 0 8px}}.session-table{{width:100%;border-collapse:collapse;table-layout:fixed;min-width:0;font-size:8px}}.session-table th{{background:#17633b;color:#fff;padding:5px}}.session-table td{{padding:5px;border:1px solid #dce7de;text-align:left}}.empty{{color:#64748b;font-size:9px}}
        body.individual-sheet{{min-height:calc(100vh - 14mm);display:flex;flex-direction:column}}
        body.individual-sheet>table.specialized-timetable{{flex:1;height:100%;width:100%;table-layout:fixed}}
        body.individual-sheet>table.specialized-timetable tbody tr{{height:1px}}
        @media print{{body{{margin:0}}.actions{{display:none}}tr{{break-inside:avoid}}table{{min-width:0}}body.individual-sheet{{height:calc(100vh - 14mm);min-height:0}}body.individual-sheet>table.specialized-timetable{{height:100%;flex:1}}.extra-remedial-separate,.extra-weekend{{break-before:page}}}}
        </style></head><body class="{'individual-sheet' if view_type in ('class', 'teacher', 'room') else ''}"><div class="actions"><button onclick="window.print()">Print timetable</button></div>
        <div style="display:grid;grid-template-columns:68px 1fr 68px;align-items:center;gap:8px;margin-bottom:4px"><div>{logo_img}</div><div><h1 style="text-decoration:underline">{school_name}</h1><p style="font-size:8px;color:#405b49;margin:3px 0">{school_details_html}</p><h2 style="text-decoration:underline">{title}</h2></div><div style="text-align:right">{logo_img}</div></div>
        <p style="font-size:9px;font-weight:500;text-align:center;margin:10px 0 14px">{meta_html}</p>
        <table class="{timetable_table_class}"><thead><tr>{header_html}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>
        {dated_html}{weekday_html}{weekend_html}{export_footer}
        <script>window.addEventListener("load",()=>setTimeout(()=>window.print(),250));</script></body></html>"""
        return HTMLResponse(html)

    @app.get("/app/timetable/export/pdf")
    def timetable_export_pdf(
        request: Request,
        profile_id: int,
        view_type: str = "school",
        class_id: int = 0,
        teacher_id: int = 0,
        room_id: int = 0,
        remedial_display: str = "combined",
    ):
        remedial_display = "separate" if remedial_display == "separate" else "combined"
        school, result, error = load_view(request, profile_id, view_type, class_id, teacher_id, room_id)
        if error:
            return error
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepInFrame, Image as ReportLabImage

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)
        styles = getSampleStyleSheet()
        school_style = ParagraphStyle("DSchoolName", parent=styles["Title"], alignment=TA_CENTER, fontSize=16, leading=19, textColor=colors.HexColor("#174a31"))
        title_style = ParagraphStyle("TimetableTitle", parent=styles["Heading2"], alignment=TA_CENTER, fontSize=11, leading=14, textColor=colors.HexColor("#315b3e"))
        cell_style = ParagraphStyle("TimetableCell", parent=styles["BodyText"], fontSize=5.5, leading=6.5)
        day_style = ParagraphStyle("TimetableDay", parent=cell_style, alignment=TA_CENTER)
        header_style = ParagraphStyle("TimetableHeader", parent=styles["BodyText"], fontSize=6, leading=7, textColor=colors.white, alignment=TA_CENTER)
        break_header_style = ParagraphStyle("TimetableBreakHeader", parent=header_style, textColor=colors.HexColor("#75551d"))
        def pdf_text(value):
            return xml_escape(str(value).encode("latin-1", "replace").decode("latin-1"))
        school_name = pdf_text(str(school["name"] or "School"))
        profile_meta = str(result["profile"]["academic_year"]) + " | " + str(result["profile"]["term"])
        current_status = status_label(result["profile"])
        logo_cell = ""
        logo_src = school_logo_data(school)
        if logo_src:
            try:
                encoded = logo_src.split(",", 1)[1] if "," in logo_src else logo_src
                logo_cell = ReportLabImage(BytesIO(base64.b64decode(encoded)), width=52, height=52, kind="proportional")
            except Exception:
                logo_cell = ""
        cover_title = "MASTER TIMETABLE" if view_type == "school" else ("TEACHER " + str(result["target"]["name"]) if view_type == "teacher" else str(result["title"]).upper())
        details = "   |   ".join(pdf_text(label + ": " + value) for label,value in school_details(school))
        cover_center = [Paragraph("<u><b>" + school_name + "</b></u>", school_style)]
        if details:
            details_style = ParagraphStyle("SchoolDetails", parent=styles["Normal"], alignment=TA_CENTER, fontSize=7, leading=9)
            cover_center.append(Paragraph(details, details_style))
        cover_center.append(Paragraph("<u><b>" + pdf_text(cover_title) + "</b></u>", title_style))
        cover = Table([[logo_cell, cover_center, logo_cell]], colWidths=[60, doc.width-120, 60])
        cover.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                                   ("LEFTPADDING",(0,0),(-1,-1),2),("RIGHTPADDING",(0,0),(-1,-1),2)]))
        story = [cover]
        meta_style = ParagraphStyle("TimetableCoverMeta", parent=styles["Normal"], alignment=TA_CENTER, fontSize=8, leading=10)
        meta_line = Paragraph(
            "<b>Term:</b> " + pdf_text(result["profile"]["term"]) +
            " &nbsp;&nbsp;|&nbsp;&nbsp; <b>Year:</b> " + pdf_text(result["profile"]["academic_year"]) +
            " &nbsp;&nbsp;|&nbsp;&nbsp; <b>Status:</b> " + pdf_text(current_status),
            meta_style,
        )
        story.extend([meta_line, Spacer(1,6)])
        layout = build_export_grid(result, view_type)
        timeline = layout["timeline"]
        individual_row_height = max(24, (doc.height - 82 - 22) / max(1, len(layout["rows"]))) if view_type in ("class", "teacher", "room") else 58
        first_width = 30 if not layout["show_class_column"] else 30
        class_width = 52 if layout["show_class_column"] else 0
        if view_type == "school":
            timeline_weight = sum(0.9 if kind == "break" else 1.0 for _, kind, _ in timeline) or 1
            slot_width = max(1, (doc.width - first_width - class_width) / timeline_weight)
            timeline_widths = [slot_width * (0.9 if kind == "break" else 1.0) for _, kind, _ in timeline]
        elif view_type in ("class", "teacher", "room"):
            # Individual resource sheets fill the available A4 landscape width.
            timeline_weight = sum(0.55 if kind == "break" else 1.0 for _, kind, _ in timeline) or 1
            slot_width = max(1, (doc.width - first_width) / timeline_weight)
            timeline_widths = [slot_width * (0.55 if kind == "break" else 1.0) for _, kind, _ in timeline]
        else:
            # Teacher and room exports retain their compact specialized layout.
            slot_width = 28
            timeline_widths = [12 if kind == "break" else slot_width for _, kind, _ in timeline]
        first_day_rows = layout["rows"][:max(1, layout["rows"][0]["day_rowspan"])]
        # Individual class, teacher, and room sheets use one continuous table so
        # each merged break label spans every instructional day.
        rows_per_day = (len(layout["rows"]) if view_type in ("class", "teacher", "room")
                        else max(1, len(first_day_rows)))
        widths = [first_width] + ([class_width] if layout["show_class_column"] else []) + timeline_widths

        # Render each day as its own full-width table. This keeps each day's
        # merged break column intact while allowing the timetable to continue
        # onto further landscape pages without shrinking the whole grid.
        from reportlab.platypus import PageBreak
        for day_start in range(0, len(layout["rows"]), rows_per_day):
            day_rows = layout["rows"][day_start:day_start + rows_per_day]
            data = [[Paragraph("Day", header_style)] + ([Paragraph("Class / Stream", header_style)] if layout["show_class_column"] else [])]
            for _, kind, item in timeline:
                label = (pdf_text(str(item["start_time"])) + "–" + pdf_text(str(item["end_time"]))) if kind == "break" else ("<b>" + pdf_text(str(item["label"])) + "</b><br/>" + pdf_text(str(item["start_time"])) + "–" + pdf_text(str(item["end_time"])))
                data[0].append(Paragraph(label, break_header_style if kind == "break" else header_style))
            span_commands = []
            for day_row_index, row in enumerate(day_rows):
                row_index = day_row_index + 1
                cells = []
                if row["day_first"]:
                    cells.append(Paragraph("<b>" + pdf_text(row["day"].get("day_code") or row["day"]["day_name"]) + "</b>", day_style))
                    if row["day_rowspan"] > 1:
                        span_commands.append(("SPAN", (0, row_index), (0, row_index + row["day_rowspan"] - 1)))
                else:
                    cells.append("")
                if layout["show_class_column"]:
                    cl = row["class"]
                    cells.append(Paragraph("<b>" + pdf_text(cl["class_name"] + ((" " + cl["stream"]) if cl["stream"] else "")) + "</b>", cell_style))
                timeline_cursor = 0
                for original_cell in row["cells"]:
                    cell = original_cell
                    if cell["kind"] == "break_placeholder":
                        timeline_entry = timeline[timeline_cursor]
                        if timeline_entry[1] == "break" and day_row_index == 0:
                            cell = {"kind": "break", "item": timeline_entry[2], "rowspan": len(day_rows)}
                        else:
                            cells.append("")
                            timeline_cursor += 1
                            continue
                    if cell["kind"] == "break":
                        if day_row_index == 0:
                            cell = dict(cell, rowspan=len(day_rows))
                        b = cell["item"]
                        break_label = "<br/>".join(pdf_text(ch) for ch in str(b["label"]))
                        break_style = ParagraphStyle("ExportBreak", parent=cell_style, alignment=TA_CENTER, fontSize=10, leading=11, textColor=colors.HexColor("#75551d"))
                        cells.append(Paragraph("<b>" + break_label + "</b>", break_style))
                        if cell["rowspan"] > 1:
                            col = len(cells) - 1
                            span_commands.append(("SPAN", (col, row_index), (col, row_index + cell["rowspan"] - 1)))
                    elif cell["kind"] == "free":
                        cells.append(Paragraph("", cell_style) if view_type in ("teacher", "room") else Paragraph("—", cell_style))
                    elif cell["kind"] == "continued":
                        cells.append(Paragraph("<br/>".join("↳ " + pdf_text(str(x.get("subject_initial") or "").strip().upper() or "—") + " continues" for x in cell["lessons"]), cell_style))
                    else:
                        card_tables = []
                        card_width = max(1, slot_width * cell["span"] - 8)
                        for lesson in cell["lessons"]:
                            subject_initial = pdf_text(str(lesson.get("subject_initial") or "").strip().upper() or "—")
                            teacher_initials = str(lesson.get("teacher_initials") or "").strip().upper()
                            if not teacher_initials:
                                name_parts = [part for part in str(lesson.get("teacher_name") or "").split() if part]
                                teacher_initials = "".join(part[0] for part in (name_parts[:1] + (name_parts[-1:] if len(name_parts) > 1 else []))).upper()[:4] or "—"
                            allocated_room = allocated_room_name(lesson)
                            room_text = "" if layout["room_view"] or not allocated_room else pdf_text(allocated_room)
                            card_color = str(lesson.get("teacher_color") or "").strip()
                            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", card_color):
                                card_color = "#2563EB"
                            accent = colors.HexColor(card_color)
                            tint = colors.Color(1-(1-accent.red)*0.17, 1-(1-accent.green)*0.17, 1-(1-accent.blue)*0.17)
                            top_style = ParagraphStyle("ExportDuration", parent=cell_style, alignment=2, fontSize=5, leading=6)
                            subject_style = ParagraphStyle("ExportSubject", parent=cell_style, alignment=TA_CENTER, fontSize=9, leading=11)
                            room_style = ParagraphStyle("ExportRoom", parent=cell_style, alignment=TA_CENTER, fontSize=5, leading=6, textColor=colors.HexColor("#55705d"))
                            teacher_style = ParagraphStyle("ExportTeacher", parent=cell_style, alignment=2, fontSize=5, leading=6, textColor=colors.white)
                            class_label = str(lesson.get("class_name") or "").strip()
                            stream_label = str(lesson.get("stream") or "").strip()
                            class_full = class_label + ((" " + stream_label) if stream_label else "")
                            class_initials = str(lesson.get("class_initials") or "").strip().upper() or class_full or "—"
                            footer_style = ParagraphStyle("ExportCellFooter", parent=teacher_style, alignment=2, fontSize=5, leading=6)
                            if view_type in ("teacher", "room"):
                                resource_subject_style = ParagraphStyle("ResourceSubject", parent=cell_style, alignment=TA_LEFT, fontSize=8, leading=9, wordWrap=None, splitLongWords=0, textColor=colors.HexColor("#365b40"))
                                resource_period_style = ParagraphStyle("ResourcePeriod", parent=cell_style, alignment=TA_RIGHT, fontSize=7, leading=8, wordWrap=None, textColor=colors.HexColor("#536b58"))
                                resource_class_style = ParagraphStyle("ResourceClass", parent=cell_style, alignment=TA_CENTER, fontSize=25, leading=27, textColor=colors.HexColor("#263f30"))
                                resource_meta = allocated_room if view_type == "teacher" else teacher_initials
                                resource_card_height = max(28, (individual_row_height - 8) / max(1, len(cell["lessons"])))
                                card_rows = [
                                    [
                                        Paragraph("<b>" + subject_initial + "</b>", resource_subject_style),
                                        "",
                                        Paragraph(pdf_text(str(max(1, int(lesson.get("duration_periods") or 1))) + "P"), resource_period_style) if view_type == "room" else "",
                                    ],
                                    [Paragraph("<b>" + pdf_text(class_initials) + "</b>", resource_class_style), "", ""],
                                    [
                                        Paragraph(pdf_text(resource_meta), footer_style) if resource_meta else "",
                                        "",
                                        Paragraph(pdf_text(str(max(1, int(lesson.get("duration_periods") or 1))) + "P"), resource_period_style) if view_type == "teacher" else "",
                                    ],
                                ]
                            else:
                                card_rows = [
                                    [Paragraph(str(max(1, int(lesson.get("duration_periods") or 1))) + "P", top_style)],
                                    [Paragraph("<b>" + subject_initial + "</b>", subject_style)],
                                ]
                                if room_text:
                                    card_rows.append([Paragraph("⌂ " + room_text, room_style)])
                                footer_label = teacher_initials
                                card_rows.append([Paragraph("<font backColor='#245b39' color='white'><b>" + pdf_text(footer_label) + "</b></font>", footer_style)])
                            card = Table(
                                card_rows,
                                colWidths=([card_width * 0.30, card_width * 0.40, card_width * 0.30] if view_type in ("teacher", "room") else [card_width]),
                                rowHeights=(
                                    [resource_card_height * 0.20, resource_card_height * 0.60, resource_card_height * 0.20]
                                    if view_type in ("teacher", "room") else
                                    [max(4, (individual_row_height - 8) / (len(card_rows) * max(1, len(cell["lessons"]))))] * len(card_rows)
                                )
                                if view_type in ("class", "teacher", "room") else None,
                            )
                            card.setStyle(TableStyle([
                                ("SPAN", (0,0), (1,0)) if view_type in ("teacher", "room") else ("ALIGN", (0,0), (-1,-1), "CENTER"),
                                ("SPAN", (0,1), (2,1)) if view_type in ("teacher", "room") else ("ALIGN", (0,0), (-1,-1), "CENTER"),
                                ("VALIGN", (0,2), (-1,2), "MIDDLE") if view_type in ("teacher", "room") else ("ALIGN", (0,0), (-1,-1), "CENTER"),
                                ("BACKGROUND", (0,0), (-1,-1), tint),
                                ("BOX", (0,0), (-1,-1), 0.45, accent),
                                ("LINEBEFORE", (0,0), (0,-1), 3, accent),
                                ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (0,0), (-1,-1), 3),
                                ("TOPPADDING", (0,0), (-1,-1), 1), ("BOTTOMPADDING", (0,0), (-1,-1), 1),
                                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                            ]))
                            card_tables.append(card)
                        if len(card_tables) == 1:
                            cells.append(card_tables[0])
                        else:
                            stack = Table([[card] for card in card_tables], colWidths=[card_width])
                            stack.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1)]))
                            cells.append(stack)
                        if cell["span"] > 1:
                            col = len(cells) - 1
                            span_commands.append(("SPAN", (col, row_index), (col + cell["span"] - 1, row_index)))
                            cells.extend([""] * (cell["span"] - 1))
                    timeline_cursor += cell.get("span", 1)
                data.append(cells)
            table = Table(data, colWidths=widths, repeatRows=1)
            if view_type in ("class", "teacher", "room"):
                # Keep the cover details compact and stretch the timetable
                # through the remaining landscape page instead of leaving
                # unused space beneath naturally-sized lesson rows.
                table.wrap(doc.width, doc.height)
                natural_heights = list(table._rowHeights)
                header_height = natural_heights[0] if natural_heights else 22
                target_grid_height = max(header_height, doc.height - 82)
                equal_data_row_height = max(24, (target_grid_height - header_height) / max(1, len(day_rows)))
                table = Table(
                    data,
                    colWidths=widths,
                    rowHeights=[header_height] + [equal_data_row_height] * len(day_rows),
                    repeatRows=1,
                )
            commands = [
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17633b")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#cbd8ce")),
                ("BACKGROUND", (0,1), (0,-1), colors.HexColor("#eef5ef")),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (0,0), (-1,-1), 3),
                ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ] + span_commands
            for col, (_, kind, _) in enumerate(timeline, start=1 + (1 if layout["show_class_column"] else 0)):
                if kind == "break":
                    commands += [("BACKGROUND", (col,0), (col,-1), colors.HexColor("#f1ead8")), ("TEXTCOLOR", (col,0), (col,-1), colors.HexColor("#75551d"))]
            table.setStyle(TableStyle(commands))
            story.append(table)
            if day_start + rows_per_day < len(layout["rows"]):
                story.append(Spacer(1, 5))

        if view_type in ("class", "teacher", "room"):
            # Keep cover, metadata, and the complete individual timetable together.
            story = [KeepInFrame(doc.width, doc.height, story, mode="shrink", hAlign="CENTER", vAlign="TOP")]

        if result.get("dated_instructional_sessions"):
            from reportlab.platypus import PageBreak
            story.append(PageBreak())
            story.append(Paragraph("CALENDAR-DATED INSTRUCTIONAL LESSONS", title_style))
            dated_rows = [[Paragraph("<b>Date / Day</b>",header_style),Paragraph("<b>Time</b>",header_style),Paragraph("<b>Subject / Activity</b>",header_style),Paragraph("<b>Class / Group</b>",header_style),Paragraph("<b>Teacher(s)</b>",header_style),Paragraph("<b>Venue</b>",header_style)]]
            for item in result["dated_instructional_sessions"]:
                dated_rows.append([
                    Paragraph(pdf_text((item.get("session_date") or "") + (" · " + str(item.get("day_name")) if item.get("day_name") else "")),cell_style),
                    Paragraph(pdf_text(str(item["start_time"])+"–"+str(item["end_time"])),cell_style),
                    Paragraph(pdf_text(item.get("subject_name") or item.get("programme_name") or item.get("session_type") or "Lesson"),cell_style),
                    Paragraph(pdf_text(item.get("class_names") or "—"),cell_style),
                    Paragraph(pdf_text(item.get("teacher_names") or "—"),cell_style),
                    Paragraph(pdf_text(item.get("room_name") or "—"),cell_style),
                ])
            dated_table = Table(dated_rows,colWidths=[doc.width*.16,doc.width*.13,doc.width*.20,doc.width*.18,doc.width*.18,doc.width*.15],repeatRows=1)
            dated_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17633b")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#cbd8ce")),("VALIGN",(0,0),(-1,-1),"TOP"),("FONTSIZE",(0,1),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
            story.append(dated_table)

        def session_paragraphs(items, rotation=False):
            values = []
            for item in items:
                heading = (str(item.get("rotation_label") or "Weekend rotation") + " · ") if rotation else ""
                title = str(item.get("subject_name") or item.get("programme_name") or item.get("session_type") or "Session")
                detail = " | ".join(filter(None, [
                    str(item.get("session_date") or item.get("day_name") or "Weekly"),
                    str(item["start_time"]) + "–" + str(item["end_time"]),
                    str(item.get("class_names") or ""),
                    str(item.get("teacher_names") or ""),
                    str(item.get("room_name") or ""),
                ]))
                values.append(Paragraph("<b>"+pdf_text(heading+title)+"</b><br/>"+pdf_text(detail), cell_style))
            return values

        if result.get("weekday_remedials"):
            from reportlab.platypus import PageBreak
            if remedial_display == "separate":
                story.append(PageBreak())
            story.append(Paragraph("WEEKDAY REMEDIAL & STUDY SESSIONS", title_style))
            remedial_rows = [[Paragraph("<b>Date / Day</b>",header_style),Paragraph("<b>Time</b>",header_style),Paragraph("<b>Programme / Subject</b>",header_style),Paragraph("<b>Class</b>",header_style),Paragraph("<b>Teacher(s)</b>",header_style),Paragraph("<b>Venue</b>",header_style)]]
            for item in result["weekday_remedials"]:
                remedial_rows.append([pdf_text(item.get("session_date") or item.get("day_name") or "Weekly"),
                    pdf_text(str(item["start_time"])+"–"+str(item["end_time"])),
                    pdf_text(item.get("subject_name") or item.get("programme_name") or item.get("session_type")),
                    pdf_text(item.get("class_names") or "—"),pdf_text(item.get("teacher_names") or "—"),
                    pdf_text(item.get("room_name") or "—")])
            rt=Table(remedial_rows,colWidths=[65,70,130,100,115,75],repeatRows=1)
            rt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17633b")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#cbd8ce")),("FONTSIZE",(0,1),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP")]))
            story.append(rt)

        if result.get("weekend_sessions"):
            from reportlab.platypus import PageBreak
            story.append(PageBreak())
            story.append(Paragraph("WEEKEND LESSONS & REMEDIALS", school_style))
            story.append(Paragraph("All configured weekend rotations consolidated on one sheet", title_style))
            weekend_rows = [[
                Paragraph("<b>"+label+"</b>",header_style)
                for label in ["Rotation","Date / Day","Time","Lesson / Activity","Class / Group","Teacher(s)","Venue"]
            ]]
            for item in result["weekend_sessions"]:
                date_label = str(item.get("session_date") or item.get("day_name") or "Weekly")
                if item.get("session_date") and item.get("day_name"):
                    date_label += " · " + str(item["day_name"])
                weekend_rows.append([
                    Paragraph(pdf_text(item.get("rotation_label") or "Weekend schedule"),cell_style),
                    Paragraph(pdf_text(date_label),cell_style),
                    Paragraph(pdf_text(str(item["start_time"])+"–"+str(item["end_time"])),cell_style),
                    Paragraph(pdf_text(item.get("subject_name") or item.get("programme_name") or item.get("session_type") or "Session"),cell_style),
                    Paragraph(pdf_text(item.get("class_names") or "—"),cell_style),
                    Paragraph(pdf_text(item.get("teacher_names") or "—"),cell_style),
                    Paragraph(pdf_text(item.get("room_name") or "—"),cell_style),
                ])
            widths = [doc.width*.14,doc.width*.15,doc.width*.12,doc.width*.19,doc.width*.15,doc.width*.15,doc.width*.10]
            weekend_table = Table(weekend_rows,colWidths=widths,repeatRows=1)
            weekend_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17633b")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#b8d2bd")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
            # Keep both weekend rotations together on one A4 landscape page.
            # Shrink only this consolidated sheet when a school has many entries.
            story.append(KeepInFrame(doc.width, doc.height - 34, [weekend_table], mode="shrink", hAlign="LEFT", vAlign="TOP"))
        generated_at = datetime.now(EAT).strftime("%d %b %Y %H:%M EAT")
        def draw_export_footer(canvas, document):
            if view_type not in ("teacher", "room"):
                return
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.HexColor("#536b58"))
            canvas.drawString(doc.leftMargin, 9, "Mabale_ICT Management System · Generated: " + generated_at)
            canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 9, "Total scheduled lessons: " + str(len(result["lessons"])))
            canvas.restoreState()
        doc.build(story, onFirstPage=draw_export_footer, onLaterPages=draw_export_footer)
        buffer.seek(0)
        filename = filename_prefix(school,result) + ".pdf"
        return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=" + filename})

    @app.get("/app/timetable/export/xlsx")
    def timetable_export_xlsx(
        request: Request,
        profile_id: int,
        view_type: str = "school",
        class_id: int = 0,
        teacher_id: int = 0,
        room_id: int = 0,
        remedial_display: str = "combined",
    ):
        remedial_display = "separate" if remedial_display == "separate" else "combined"
        school, result, error = load_view(request, profile_id, view_type, class_id, teacher_id, room_id)
        if error:
            return error
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.cell.rich_text import CellRichText, TextBlock, InlineFont

        buffer = BytesIO()
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Timetable"
        from openpyxl.utils import get_column_letter
        timeline = sorted(
            [(str(p["start_time"]), "period", p) for p in result["periods"]] +
            [(str(br["start_time"]), "break", br) for br in result.get("breaks", [])],
            key=lambda item: (item[0], 0 if item[1] == "period" else 1),
        )
        last_col = 1 + (1 if view_type == 'school' else 0) + len(timeline)
        sheet.merge_cells(start_row=1,start_column=1,end_row=1,end_column=last_col)
        sheet.cell(1,1,str(school["name"] or "School"))
        sheet.cell(1,1).font = Font(bold=True,size=16,color="174A31")
        sheet.cell(1,1).alignment = Alignment(horizontal="center")
        sheet.merge_cells(start_row=2,start_column=1,end_row=2,end_column=last_col)
        sheet.cell(2,1,("TEACHER " + str(result["target"]["name"])) if view_type == "teacher" else result["title"].upper())
        sheet.cell(2,1).font = Font(bold=True,size=12,color="315B3E")
        sheet.cell(2,1).alignment = Alignment(horizontal="center")
        sheet.merge_cells(start_row=3,start_column=1,end_row=3,end_column=last_col)
        profile_text = str(result["profile"]["academic_year"]) + " · " + str(result["profile"]["term"]) + " · " + str(len(result["lessons"])) + " scheduled lessons"
        sheet.cell(3,1,profile_text)
        sheet.cell(3,1).alignment = Alignment(horizontal="center")
        header_row = 5
        headers = ["Day"] + [
            ((str(item["start_time"]) + "–" + str(item["end_time"])) if kind == "break" else (str(item["label"]) + "\n" + str(item["start_time"]) + "–" + str(item["end_time"])))
            for _, kind, item in timeline
        ]
        for col, value in enumerate(headers,1):
            cell = sheet.cell(header_row,col,value)
            cell.font = Font(bold=True,color="FFFFFF")
            cell.fill = PatternFill("solid",fgColor="17633B")
            cell.alignment = Alignment(horizontal="center",vertical="center",wrap_text=True)
        layout=build_export_grid(result,view_type)
        timeline=layout["timeline"]
        headers=["Day"]+([ "Class / Stream" ] if layout["show_class_column"] else [])+[((str(item["start_time"])+"–"+str(item["end_time"])) if kind=="break" else (str(item["label"])+"\n"+str(item["start_time"])+"–"+str(item["end_time"]))) for _,kind,item in timeline]
        for col,value in enumerate(headers,1):
            c=sheet.cell(header_row,col,value); c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="17633B"); c.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
        break_columns=set()
        lesson_color_cells=[]
        row_index=header_row+1
        for row in layout["rows"]:
            col=1
            if row["day_first"]:
                day_cell = sheet.cell(row_index,col,row["day"]["day_name"])
                day_cell.alignment = Alignment(horizontal="center",vertical="center",wrap_text=True)
                if row["day_rowspan"]>1: sheet.merge_cells(start_row=row_index,start_column=col,end_row=row_index+row["day_rowspan"]-1,end_column=col)
            col+=1
            if layout["show_class_column"]:
                cl=row["class"]; sheet.cell(row_index,col,cl["class_name"]+((" "+cl["stream"]) if cl["stream"] else "")); col+=1
            for cell in row["cells"]:
                if cell["kind"]=="break_placeholder":
                    col += 1
                    continue
                target=sheet.cell(row_index,col)
                if cell["kind"]=="break":
                    b=cell["item"]; target.value="\n".join(str(ch) for ch in str(b["label"]))
                    target.fill=PatternFill("solid",fgColor="F1EAD8"); target.font=Font(bold=True,color="75551D")
                    target.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
                    if cell["rowspan"]>1: sheet.merge_cells(start_row=row_index,start_column=col,end_row=row_index+cell["rowspan"]-1,end_column=col)
                elif cell["kind"]=="continued":
                    target.value="\n".join("↳ "+str(x.get("subject_initial") or "").strip().upper()+" continues" for x in cell["lessons"])
                elif cell["kind"]=="lesson":
                    values=[]
                    for lesson in cell["lessons"]:
                        teacher_initials=str(lesson.get("teacher_initials") or "").strip().upper()
                        if not teacher_initials:
                            name_parts=[part for part in str(lesson.get("teacher_name") or "").split() if part]
                            teacher_initials="".join(part[0] for part in (name_parts[:1]+(name_parts[-1:] if len(name_parts)>1 else []))).upper()[:4] or "—"
                        allocated_room=allocated_room_name(lesson)
                        if view_type in ("teacher", "room"):
                            class_label=str(lesson.get("class_name") or "").strip()
                            stream_label=str(lesson.get("stream") or "").strip()
                            class_initials=str(lesson.get("class_initials") or "").strip().upper() or (class_label+((" "+stream_label) if stream_label else "") or "—")
                            resource_meta=allocated_room if view_type == "teacher" else teacher_initials
                            period_label=str(max(1,int(lesson.get("duration_periods") or 1)))+"P"
                            subject_label=str(lesson.get("subject_initial") or "").strip().upper()
                            detail=CellRichText([
                                TextBlock(InlineFont(rFont="Consolas",sz=7,b=True), subject_label + (" " * 4 + period_label if view_type == "room" else "")),
                                "\n",
                                TextBlock(InlineFont(rFont="Arial",sz=25,b=True,color="263F30"), class_initials),
                                "\n",
                                TextBlock(InlineFont(rFont="Arial",sz=8,b=True,color="536B58"), resource_meta or ""),
                                "\n",
                                TextBlock(InlineFont(rFont="Arial",sz=8,b=True,color="536B58"), (" " * 8 + period_label) if view_type == "teacher" else ""),
                            ])
                        else:
                            detail=str(max(1,int(lesson.get("duration_periods") or 1)))+"P\n"+str(lesson.get("subject_initial") or "").strip().upper()+"\n"
                            if not layout["room_view"] and allocated_room: detail+="⌂ "+allocated_room+"\n"
                            detail+=teacher_initials
                        values.append(detail)
                    if view_type in ("teacher", "room"):
                        rich_content = CellRichText()
                        for value_index, value in enumerate(values):
                            if value_index:
                                rich_content.append("\n\n")
                            rich_content.extend(value)
                        target.value = rich_content
                    else:
                        target.value="\n\n".join(values)
                    lesson_colors={teacher_color_hex(lesson.get("teacher_color")) for lesson in cell["lessons"]}
                    if len(lesson_colors)==1:
                        lesson_color_cells.append((row_index,col,next(iter(lesson_colors))))
                    if cell["span"]>1: sheet.merge_cells(start_row=row_index,start_column=col,end_row=row_index,end_column=col+cell["span"]-1)
                target.alignment=Alignment(wrap_text=view_type not in ("teacher", "room"),vertical="center",horizontal="center")
                if cell["kind"]=="break": break_columns.add(col)
                col += cell.get("span",1)
            sheet.row_dimensions[row_index].height=66 if view_type in ("teacher", "room") else 58
            row_index+=1
        last_col=1+(1 if layout["show_class_column"] else 0)+len(timeline)
        sheet.column_dimensions["A"].width = 9
        if layout["show_class_column"]:
            sheet.column_dimensions["B"].width = 14
        for col in range(2+(1 if layout["show_class_column"] else 0),last_col+1):
            kind = timeline[col - (2 if layout["show_class_column"] else 1) - 1][1]
            if view_type == "school":
                column_width = 19.8 if kind == "break" else 22
            else:
                column_width = 5.5 if kind == "break" else (16 if view_type in ("teacher", "room") else 10)
            sheet.column_dimensions[get_column_letter(col)].width = column_width
        sheet.freeze_panes = "B6"
        sheet.sheet_view.showGridLines = False
        sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(last_col)}{row_index-1}"


        if result.get("dated_instructional_sessions"):
            dated = workbook.create_sheet("Dated Lessons")
            dated_headers = ["Date","Day","Start","End","Subject / Activity","Class / Group","Teacher(s)","Venue"]
            dated.append(dated_headers)
            for cell in dated[1]:
                cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="17633B")
            for item in result["dated_instructional_sessions"]:
                dated.append([item.get("session_date") or "",item.get("day_name") or "",item["start_time"],item["end_time"],item.get("subject_name") or item.get("programme_name") or item.get("session_type"),item.get("class_names") or "—",item.get("teacher_names") or "—",item.get("room_name") or "—"])
            dated.freeze_panes="A2"; dated.auto_filter.ref=dated.dimensions
            for col in range(1,len(dated_headers)+1):
                dated.column_dimensions[get_column_letter(col)].width=22
            dated.sheet_properties.pageSetUpPr.fitToPage=True
            dated.page_setup.orientation="landscape"; dated.page_setup.paperSize=dated.PAPERSIZE_A4
            dated.page_setup.fitToWidth=1; dated.page_setup.fitToHeight=0

        if result.get("weekday_remedials") and remedial_display == "combined":
            sheet.cell(row_index + 1,1,"WEEKDAY REMEDIAL & STUDY SESSIONS").font = Font(bold=True,size=12,color="17633B")
            remedial_headers = ["Date / Day","Start","End","Programme / Subject","Class / Group","Teacher(s)","Venue"]
            for col,value in enumerate(remedial_headers,1):
                cell=sheet.cell(row_index+2,col,value); cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="17633B")
            for offset,item in enumerate(result["weekday_remedials"],row_index+3):
                for col,value in enumerate([item.get("session_date") or item.get("day_name") or "Weekly",item["start_time"],item["end_time"],item.get("subject_name") or item.get("programme_name") or item.get("session_type"),item.get("class_names") or "—",item.get("teacher_names") or "—",item.get("room_name") or "—"],1):
                    sheet.cell(offset,col,value).alignment=Alignment(wrap_text=True,vertical="top")
        if result.get("weekend_sessions"):
            weekend = workbook.create_sheet("Weekend Lessons")
            weekend_headers = ["Weekend rotation","Date","Day","Start","End","Programme / Subject","Class / Group","Teacher(s)","Venue","Layer"]
            weekend.append(weekend_headers)
            for cell in weekend[1]:
                cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="17633B")
            for item in result["weekend_sessions"]:
                weekend.append([item.get("rotation_label") or "Weekend rotation",item.get("session_date") or "",item.get("day_name") or "",item["start_time"],item["end_time"],item.get("subject_name") or item.get("programme_name") or item.get("session_type"),item.get("class_names") or "—",item.get("teacher_names") or "—",item.get("room_name") or "—",item.get("schedule_layer")])
            weekend.freeze_panes="A2"; weekend.auto_filter.ref=weekend.dimensions
            for col in range(1,len(weekend_headers)+1):
                weekend.column_dimensions[get_column_letter(col)].width=20
            weekend.sheet_properties.pageSetUpPr.fitToPage=True
            weekend.page_setup.orientation="landscape"; weekend.page_setup.paperSize=weekend.PAPERSIZE_A4
            weekend.page_setup.fitToWidth=1; weekend.page_setup.fitToHeight=1
            weekend.print_area="A1:J" + str(weekend.max_row)
            weekend.sheet_properties.pageSetUpPr.autoPageBreaks=False
        if result.get("weekday_remedials") and remedial_display == "separate":
            remedial = workbook.create_sheet("Weekday Remedials")
            remedial_headers=["Date / Day","Start","End","Programme / Subject","Class / Group","Teacher(s)","Venue"]
            remedial.append(remedial_headers)
            for cell in remedial[1]:
                cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="17633B")
            for item in result["weekday_remedials"]:
                remedial.append([item.get("session_date") or item.get("day_name") or "Weekly",item["start_time"],item["end_time"],item.get("subject_name") or item.get("programme_name") or item.get("session_type"),item.get("class_names") or "—",item.get("teacher_names") or "—",item.get("room_name") or "—"])
            remedial.freeze_panes="A2"; remedial.auto_filter.ref=remedial.dimensions
            for col in range(1,len(remedial_headers)+1):
                remedial.column_dimensions[get_column_letter(col)].width=22

        details = workbook.create_sheet("Lesson Details")
        detail_headers = ["Day","Period","Start","End","Class","Stream","Subject","Teacher","Room","Duration"]
        details.append(detail_headers)
        for cell in details[1]:
            cell.font = Font(bold=True,color="FFFFFF")
            cell.fill = PatternFill("solid",fgColor="17633B")
        for lesson in result["lessons"]:
            details.append([
                lesson["day_name"],lesson["period_label"],lesson["start_time"],lesson["end_time"],
                lesson["class_name"],lesson["stream"],lesson["subject_name"],lesson["teacher_name"],
                lesson["room_name"],lesson["duration_periods"],
            ])
        details.freeze_panes = "A2"
        details.auto_filter.ref = details.dimensions
        for col in range(1,len(detail_headers)+1):
            details.column_dimensions[chr(64+col)].width = 20
        thin = Side(style="thin",color="DCE7DE")
        for ws in (sheet,details):
            for row in ws.iter_rows():
                for cell in row:
                    cell.border = Border(bottom=thin)
        # Reapply teacher accents after the shared grid borders.
        for lesson_row, lesson_col, accent in lesson_color_cells:
            target=sheet.cell(lesson_row,lesson_col)
            target.fill=PatternFill("solid",fgColor=teacher_tint_hex(accent))
            target.border=Border(left=Side(style="medium",color=accent[1:]),bottom=thin)
        # Keep every worksheet printable on standard A4 paper. Wide timetables
        # and details scale to one page wide; weekend rotations remain a single
        # consolidated A4 page as explicitly requested.
        for ws in workbook.worksheets:
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.orientation = "landscape"
            ws.page_setup.paperSize = ws.PAPERSIZE_A4
            ws.page_setup.fitToWidth = 1
            if ws.title == "Weekend Lessons":
                ws.page_setup.fitToHeight = 1
                ws.sheet_properties.pageSetUpPr.autoPageBreaks = False
                ws.print_area = "A1:J" + str(ws.max_row)
            elif view_type in ("class", "teacher", "room") and ws is sheet:
                ws.page_setup.fitToHeight = 1
                ws.sheet_properties.pageSetUpPr.autoPageBreaks = False
                ws.print_area = "A1:" + get_column_letter(last_col) + str(row_index - 1)
            else:
                ws.page_setup.fitToHeight = 0

        if view_type in ("teacher", "room"):
            generated_at = datetime.now(EAT).strftime("%d %b %Y %H:%M EAT")
            sheet.oddFooter.left.text = "Mabale_ICT Management System · Generated: " + generated_at
            sheet.oddFooter.right.text = "Total scheduled lessons: " + str(len(result["lessons"]))
            sheet.oddFooter.left.size = 8
            sheet.oddFooter.right.size = 8
        workbook.save(buffer)
        buffer.seek(0)
        filename = filename_prefix(school,result) + ".xlsx"
        return StreamingResponse(buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=" + filename})
