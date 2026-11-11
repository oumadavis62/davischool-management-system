"""Printable PDF and Excel timetable exports."""
from __future__ import annotations

from io import BytesIO
from html import escape
import logging
import re
from xml.sax.saxutils import escape as xml_escape

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from app.timetable.views import get_timetable_view
from app.timetable.setup import TimetableSetupError
from app.timetable.export_grid import build_export_grid

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
        return (safe or "DaviSchool-Timetable")[:90]

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
        headers += [str(item["label"]) + "<br>" + str(item["start_time"]) + "–" + str(item["end_time"]) for _,_,item in timeline]
        body_rows = []
        for row in layout["rows"]:
            cells = []
            if row["day_first"]:
                cells.append(f"<th rowspan='{row['day_rowspan']}' class='day'>{escape(str(row['day']['day_name']))}</th>")
            if layout["show_class_column"]:
                cl=row["class"]
                cells.append("<th class='class'>" + escape(cl["class_name"] + ((" " + cl["stream"]) if cl["stream"] else "")) + "</th>")
            for cell in row["cells"]:
                if cell["kind"] == "break_placeholder":
                    continue
                if cell["kind"] == "break":
                    b=cell["item"]
                    cells.append(f"<td class='break' rowspan='{cell['rowspan']}'><b>{escape(str(b['label']))}</b><br>{escape(str(b['start_time']))}–{escape(str(b['end_time']))}</td>")
                elif cell["kind"] == "free":
                    cells.append("<td class='free'></td>")
                elif cell["kind"] == "continued":
                    labels=[]
                    for lesson in cell["lessons"]:
                        labels.append("↳ " + escape(str(lesson["subject_name"])) + " continues")
                    cells.append("<td class='continued'>" + "<br>".join(labels) + "</td>")
                else:
                    cards=[]
                    for lesson in cell["lessons"]:
                        subject=escape(str(lesson["subject_name"]))
                        initials=escape(str(lesson.get("subject_initial") or subject[:3]).upper())
                        detail=f"<b>{initials}</b> · {subject}<small>{int(lesson['duration_periods'] or 1)} period(s)</small>"
                        if layout["resource_view"]:
                            cl=escape(str(lesson["class_name"]) + ((" " + str(lesson["stream"])) if lesson["stream"] else ""))
                            detail += f"<small>{cl}</small>"
                        if view_type != "teacher":
                            detail += f"<small>{escape(str(lesson['teacher_name']))}</small>"
                        if not layout["room_view"] and lesson.get("room_name"):
                            detail += f"<small>⌂ {escape(str(lesson['room_name']))}</small>"
                        card_color = str(lesson.get("teacher_color") or "").strip()
                        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", card_color):
                            card_color = "#2563EB"
                        cards.append("<div class='lesson' style='--teacher-color:" + card_color + "'>" + detail + "</div>")
                    cells.append(f"<td class='slot' colspan='{cell['span']}'>" + "".join(cards) + "</td>")
            body_rows.append("<tr>" + "".join(cells) + "</tr>")
        school_name=escape(str(field_value(school,"name","School")))
        title=escape(str(result["title"]))
        meta=escape(str(result["profile"]["academic_year"]) + " · " + str(result["profile"]["term"]))
        header_html="".join("<th>"+h+"</th>" for h in headers)
        html=f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
        <style>
        @page{{size:A4 landscape;margin:7mm}}*{{box-sizing:border-box}}body{{font:10px Arial,sans-serif;color:#234638;margin:12px}}
        h1,h2,p{{text-align:center;margin:3px}}h1{{font-size:17px}}h2{{font-size:13px}}p{{color:#647b6a;margin-bottom:12px}}
        table{{width:100%;border-collapse:collapse;table-layout:fixed;min-width:900px}}th,td{{border:1px solid #c7d9ca;padding:4px;text-align:center;vertical-align:middle;overflow-wrap:anywhere}}
        thead th{{background:#347b50;color:white;font-size:9px;padding:7px 3px}}th.day{{background:#edf5ee;color:#315b3e;width:65px}}th.class{{background:#f5f9f5;color:#315b3e;width:65px}}
        td.slot{{background:#fff}}.lesson{{background:color-mix(in srgb,var(--teacher-color) 17%,white);border:1px solid color-mix(in srgb,var(--teacher-color) 48%,white);border-left:4px solid var(--teacher-color);border-radius:6px;padding:5px;margin:2px;font-size:9px;line-height:1.35}}
        .lesson small{{display:block;color:#55705d;font-size:8px;margin-top:2px}}td.free{{background:#fbfdfb}}td.continued{{background:#f6faf6;color:#7b9480;font-size:8px}}
        td.break{{background:#f1ead8;color:#75551d;font-weight:bold}}.actions{{text-align:center;margin-bottom:10px}}button{{padding:8px 15px;background:#17633b;color:#fff;border:0;border-radius:7px}}
        @media print{{body{{margin:0}}.actions{{display:none}}tr{{break-inside:avoid}}table{{min-width:0}}}}
        </style></head><body><div class="actions"><button onclick="window.print()">Print timetable</button></div>
        <h1>{school_name}</h1><h2>{title}</h2><p>{meta}</p><table><thead><tr>{header_html}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>
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
        from reportlab.lib.enums import TA_CENTER
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepInFrame

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)
        styles = getSampleStyleSheet()
        school_style = ParagraphStyle("DaviSchoolName", parent=styles["Title"], alignment=TA_CENTER, fontSize=16, leading=19, textColor=colors.HexColor("#174a31"))
        title_style = ParagraphStyle("TimetableTitle", parent=styles["Heading2"], alignment=TA_CENTER, fontSize=11, leading=14, textColor=colors.HexColor("#315b3e"))
        cell_style = ParagraphStyle("TimetableCell", parent=styles["BodyText"], fontSize=5.5, leading=6.5)
        header_style = ParagraphStyle("TimetableHeader", parent=styles["BodyText"], fontSize=6, leading=7, textColor=colors.white, alignment=TA_CENTER)
        def pdf_text(value):
            return xml_escape(str(value).encode("latin-1", "replace").decode("latin-1"))
        school_name = pdf_text(str(school["name"] or "School"))
        address = pdf_text(str(field_value(school, "address", field_value(school, "location", "")) or ""))
        story = [Paragraph(school_name, school_style)]
        if address:
            story.append(Paragraph(address, styles["Normal"]))
        profile_meta = str(result["profile"]["academic_year"]) + " | " + str(result["profile"]["term"])
        story.extend([
            Spacer(1,5),
            Paragraph(pdf_text(result["title"]).upper(), title_style),
            Paragraph(pdf_text(profile_meta), styles["Normal"]),
            Spacer(1,10),
        ])
        layout = build_export_grid(result, view_type)
        timeline = layout["timeline"]
        first_width = 42 if not layout["show_class_column"] else 76
        class_width = 65 if layout["show_class_column"] else 0
        slot_width = max(1, (doc.width - first_width - class_width) / max(1, len(timeline)))
        data = [[Paragraph("Day", header_style)] + ([Paragraph("Class / Stream",header_style)] if layout["show_class_column"] else [])]
        for _, kind, item in timeline:
            label = "<b>" + pdf_text(str(item["label"])) + "</b><br/>" + pdf_text(str(item["start_time"])) + "–" + pdf_text(str(item["end_time"]))
            data[0].append(Paragraph(label, header_style))
        span_commands=[]
        for row_index, row in enumerate(layout["rows"], start=1):
            cells=[]
            if row["day_first"]:
                cells.append(Paragraph("<b>"+pdf_text(row["day"]["day_name"])+"</b>",cell_style))
                if row["day_rowspan"]>1:
                    span_commands.append(("SPAN",(0,row_index),(0,row_index+row["day_rowspan"]-1)))
            else:
                cells.append("")
            if layout["show_class_column"]:
                cl=row["class"]
                cells.append(Paragraph("<b>"+pdf_text(cl["class_name"] + ((" "+cl["stream"]) if cl["stream"] else ""))+"</b>",cell_style))
            for cell in row["cells"]:
                if cell["kind"]=="break_placeholder":
                    cells.append("")
                elif cell["kind"]=="break":
                    b=cell["item"]
                    cells.append(Paragraph("<b>"+pdf_text(b["label"])+"</b><br/>"+pdf_text(b["start_time"]+"–"+b["end_time"]),cell_style))
                    if cell["rowspan"]>1:
                        col=len(cells)-1
                        span_commands.append(("SPAN",(col,row_index),(col,row_index+cell["rowspan"]-1)))
                elif cell["kind"]=="free":
                    cells.append(Paragraph("—",cell_style))
                elif cell["kind"]=="continued":
                    cells.append(Paragraph("<br/>".join("↳ "+pdf_text(x["subject_name"])+" continues" for x in cell["lessons"]),cell_style))
                else:
                    card_tables=[]
                    card_width=max(1,slot_width*cell["span"]-8)
                    for lesson in cell["lessons"]:
                        class_label=str(lesson["class_name"])+((" "+str(lesson["stream"])) if lesson["stream"] else "")
                        detail="<b>"+pdf_text(lesson["subject_name"])+"</b><br/>"+pdf_text(str(lesson["duration_periods"])+" period(s)")
                        if layout["resource_view"]: detail += "<br/>"+pdf_text(class_label)
                        if view_type!="teacher": detail += "<br/>"+pdf_text(lesson["teacher_name"])
                        if not layout["room_view"] and lesson.get("room_name"): detail += "<br/>"+pdf_text(lesson["room_name"])
                        card_color=str(lesson.get("teacher_color") or "").strip()
                        if not re.fullmatch(r"#[0-9A-Fa-f]{6}",card_color):
                            card_color="#2563EB"
                        accent=colors.HexColor(card_color)
                        tint=colors.Color(1-(1-accent.red)*0.17,1-(1-accent.green)*0.17,1-(1-accent.blue)*0.17)
                        card=Table([[Paragraph(detail,cell_style)]],colWidths=[card_width])
                        card.setStyle(TableStyle([
                            ("BACKGROUND",(0,0),(-1,-1),tint),
                            ("BOX",(0,0),(-1,-1),0.45,accent),
                            ("LINEBEFORE",(0,0),(0,-1),3,accent),
                            ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),3),
                            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
                        ]))
                        card_tables.append(card)
                    if len(card_tables)==1:
                        cells.append(card_tables[0])
                    else:
                        stack=Table([[card] for card in card_tables],colWidths=[card_width])
                        stack.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1)]))
                        cells.append(stack)
                    if cell["span"]>1:
                        col=len(cells)-1
                        span_commands.append(("SPAN",(col,row_index),(col+cell["span"]-1,row_index)))
                        cells.extend([""] * (cell["span"]-1))
            data.append(cells)
        widths=[first_width]+([class_width] if layout["show_class_column"] else [])+[slot_width]*len(timeline)
        table=Table(data,colWidths=widths,repeatRows=1)
        commands=[
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17633b")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#cbd8ce")),
            ("BACKGROUND",(0,1),(0,-1),colors.HexColor("#eef5ef")),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]+span_commands
        for col,(_,kind,_) in enumerate(timeline,start=1+(1 if layout["show_class_column"] else 0)):
            if kind=="break":
                commands += [("BACKGROUND",(col,0),(col,-1),colors.HexColor("#f1ead8")),("TEXTCOLOR",(col,0),(col,-1),colors.HexColor("#75551d"))]
        table.setStyle(TableStyle(commands))
        story.append(table)

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
        doc.build(story)
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
        sheet.cell(2,1,result["title"].upper())
        sheet.cell(2,1).font = Font(bold=True,size=12,color="315B3E")
        sheet.cell(2,1).alignment = Alignment(horizontal="center")
        sheet.merge_cells(start_row=3,start_column=1,end_row=3,end_column=last_col)
        profile_text = str(result["profile"]["academic_year"]) + " · " + str(result["profile"]["term"]) + " · " + str(len(result["lessons"])) + " scheduled lessons"
        sheet.cell(3,1,profile_text)
        sheet.cell(3,1).alignment = Alignment(horizontal="center")
        header_row = 5
        headers = ["Day"] + [
            (str(item["label"]) + "\n" + str(item["start_time"]) + "–" + str(item["end_time"]))
            for _, _, item in timeline
        ]
        for col, value in enumerate(headers,1):
            cell = sheet.cell(header_row,col,value)
            cell.font = Font(bold=True,color="FFFFFF")
            cell.fill = PatternFill("solid",fgColor="17633B")
            cell.alignment = Alignment(horizontal="center",vertical="center",wrap_text=True)
        layout=build_export_grid(result,view_type)
        timeline=layout["timeline"]
        headers=["Day"]+(["Class / Stream"] if layout["show_class_column"] else [])+[str(item["label"])+"\n"+str(item["start_time"])+"–"+str(item["end_time"]) for _,_,item in timeline]
        for col,value in enumerate(headers,1):
            c=sheet.cell(header_row,col,value); c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="17633B"); c.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
        break_columns=set()
        lesson_color_cells=[]
        row_index=header_row+1
        for row in layout["rows"]:
            col=1
            if row["day_first"]:
                sheet.cell(row_index,col,row["day"]["day_name"])
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
                    b=cell["item"]; target.value=b["label"]+"\n"+b["start_time"]+"–"+b["end_time"]
                    target.fill=PatternFill("solid",fgColor="F1EAD8"); target.font=Font(bold=True,color="75551D")
                    if cell["rowspan"]>1: sheet.merge_cells(start_row=row_index,start_column=col,end_row=row_index+cell["rowspan"]-1,end_column=col)
                elif cell["kind"]=="continued":
                    target.value="\n".join("↳ "+x["subject_name"]+" continues" for x in cell["lessons"])
                elif cell["kind"]=="lesson":
                    values=[]
                    for lesson in cell["lessons"]:
                        cl=str(lesson["class_name"])+((" "+str(lesson["stream"])) if lesson["stream"] else "")
                        detail=str(lesson["subject_name"])+" ("+str(lesson["duration_periods"])+"P)"
                        if layout["resource_view"]: detail+="\n"+cl
                        if view_type!="teacher": detail+="\n"+str(lesson["teacher_name"])
                        if not layout["room_view"] and lesson.get("room_name"): detail+="\n"+str(lesson["room_name"])
                        values.append(detail)
                    target.value="\n\n".join(values)
                    lesson_colors={teacher_color_hex(lesson.get("teacher_color")) for lesson in cell["lessons"]}
                    if len(lesson_colors)==1:
                        lesson_color_cells.append((row_index,col,next(iter(lesson_colors))))
                    if cell["span"]>1: sheet.merge_cells(start_row=row_index,start_column=col,end_row=row_index,end_column=col+cell["span"]-1)
                target.alignment=Alignment(wrap_text=True,vertical="center",horizontal="center")
                if cell["kind"]=="break": break_columns.add(col)
                col += cell.get("span",1)
            sheet.row_dimensions[row_index].height=58
            row_index+=1
        last_col=1+(1 if layout["show_class_column"] else 0)+len(timeline)
        sheet.column_dimensions["A"].width = 16
        for col in range(2,last_col+1):
            sheet.column_dimensions[get_column_letter(col)].width = 22
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
            else:
                ws.page_setup.fitToHeight = 0

        workbook.save(buffer)
        buffer.seek(0)
        filename = filename_prefix(school,result) + ".xlsx"
        return StreamingResponse(buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=" + filename})
