"""Printable PDF and Excel timetable exports."""
from __future__ import annotations

from io import BytesIO
import re
from xml.sax.saxutils import escape as xml_escape

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from app.timetable.views import get_timetable_view
from app.timetable.setup import TimetableSetupError


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

    def filename_prefix(school, result):
        raw = str(school["name"] or "School") + "-" + str(result["title"] or "Timetable")
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")
        return (safe or "DaviSchool-Timetable")[:90]

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
        from reportlab.lib.pagesizes import A3, A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A3 if result.get("weekend_sessions") else A4), leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)
        styles = getSampleStyleSheet()
        school_style = ParagraphStyle("DaviSchoolName", parent=styles["Title"], alignment=TA_CENTER, fontSize=16, leading=19, textColor=colors.HexColor("#174a31"))
        title_style = ParagraphStyle("TimetableTitle", parent=styles["Heading2"], alignment=TA_CENTER, fontSize=11, leading=14, textColor=colors.HexColor("#315b3e"))
        cell_style = ParagraphStyle("TimetableCell", parent=styles["BodyText"], fontSize=6.5, leading=8)
        header_style = ParagraphStyle("TimetableHeader", parent=styles["BodyText"], fontSize=7, leading=9, textColor=colors.white, alignment=TA_CENTER)
        def pdf_text(value):
            return xml_escape(str(value).encode("latin-1", "replace").decode("latin-1"))
        school_name = pdf_text(str(school["name"] or "School"))
        address = pdf_text(str(school["address"] or ""))
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
        starts, continued = cell_map(result)
        timeline = sorted(
            [(str(p["start_time"]), "period", p) for p in result["periods"]] +
            [(str(br["start_time"]), "break", br) for br in result.get("breaks", [])],
            key=lambda item: (item[0], 0 if item[1] == "period" else 1),
        )
        headers = [Paragraph("Day", header_style)]
        for _, item_type, item in timeline:
            headers.append(Paragraph(
                "<b>" + pdf_text(str(item["label"])) + "</b><br/>" +
                pdf_text(str(item["start_time"])) + " - " + pdf_text(str(item["end_time"])),
                header_style,
            ))
        data = [headers]
        break_col_indexes = [i + 1 for i, (_, kind, _) in enumerate(timeline) if kind == "break"]
        for day in result["days"]:
            row = [Paragraph("<b>" + pdf_text(str(day["day_name"])) + "</b>", cell_style)]
            for _, item_type, item in timeline:
                if item_type == "break":
                    row.append(Paragraph("<b>" + pdf_text(str(item["label"])) + "</b><br/>" +
                                         pdf_text(str(item["start_time"])) + " - " +
                                         pdf_text(str(item["end_time"])), cell_style))
                    continue
                key = (int(day["id"]), int(item["id"]))
                if key in starts:
                    lines = []
                    for lesson in starts[key]:
                        class_label = str(lesson["class_name"]) + ((" " + str(lesson["stream"])) if lesson["stream"] else "")
                        line = "<b>" + pdf_text(str(lesson["subject_name"])) + "</b><br/>" + pdf_text(class_label) + "<br/>" + pdf_text(str(lesson["teacher_name"]))
                        if lesson["room_name"]:
                            line += "<br/>" + pdf_text(str(lesson["room_name"]))
                        lines.append(line)
                    cell = "<br/><br/>".join(lines)
                elif key in continued:
                    cell = "Continues: " + pdf_text(str(continued[key]["subject_name"]))
                else:
                    cell = "—"
                row.append(Paragraph(cell, cell_style))
            data.append(row)
        available_width = doc.width
        first_width = 62
        slot_width = max(52, (available_width - first_width) / max(1, len(timeline)))
        table = Table(data, colWidths=[first_width] + [slot_width] * len(timeline), repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17633b")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#cbd8ce")),
            ("BACKGROUND",(0,1),(0,-1),colors.HexColor("#eef5ef")),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LEFTPADDING",(0,0),(-1,-1),4),
            ("RIGHTPADDING",(0,0),(-1,-1),4),
            ("TOPPADDING",(0,0),(-1,-1),5),
            ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ]))
        for break_col in break_col_indexes:
            table.setStyle(TableStyle([
                ("BACKGROUND",(break_col,0),(break_col,-1),colors.HexColor("#f1ead8")),
                ("TEXTCOLOR",(break_col,0),(break_col,-1),colors.HexColor("#75551d")),
            ]))
        story.append(table)

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
            from reportlab.platypus import PageBreak, KeepTogether
            story.append(PageBreak())
            story.append(Paragraph("WEEKEND LESSONS & REMEDIALS", school_style))
            story.append(Paragraph("All configured weekend rotations consolidated on one sheet", title_style))
            groups = result.get("weekend_groups", {})
            group_names = list(groups) or ["Weekend sessions"]
            columns = []
            for name in group_names:
                blocks = [Paragraph("<b>"+pdf_text(name)+"</b>", title_style)]
                blocks.extend(session_paragraphs(groups.get(name, result["weekend_sessions"]), True))
                columns.append(blocks)
            rows = []
            for i in range(0,len(columns),2):
                left = columns[i]
                right = columns[i+1] if i+1 < len(columns) else []
                rows.append([left,right])
            weekend_table = Table(rows,colWidths=[doc.width/2,doc.width/2])
            weekend_table.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.HexColor("#b8d2bd")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
            story.append(KeepTogether([weekend_table]))
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
        last_col = 1 + len(timeline)
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
        starts, continued = cell_map(result)
        break_columns = {index + 2 for index, (_, kind, _) in enumerate(timeline) if kind == "break"}
        row_index = header_row + 1
        for day in result["days"]:
            sheet.cell(row_index,1,str(day["day_name"]))
            sheet.cell(row_index,1).font = Font(bold=True,color="315B3E")
            for col, (_, item_type, item) in enumerate(timeline,2):
                cell = sheet.cell(row_index,col)
                if item_type == "break":
                    cell.value = str(item["label"])
                    cell.fill = PatternFill("solid",fgColor="F1EAD8")
                    cell.font = Font(bold=True,color="75551D")
                    cell.alignment = Alignment(horizontal="center",vertical="center",wrap_text=True)
                    continue
                key = (int(day["id"]),int(item["id"]))
                if key in starts:
                    lines = []
                    for lesson in starts[key]:
                        class_label = str(lesson["class_name"]) + ((" " + str(lesson["stream"])) if lesson["stream"] else "")
                        lines.append(str(lesson["subject_name"]) + " — " + class_label + "\n" + str(lesson["teacher_name"]) + "\n" + str(lesson["room_name"] or "No room"))
                    cell.value = "\n\n".join(lines)
                elif key in continued:
                    cell.value = "↳ " + str(continued[key]["subject_name"]) + " continues"
                else:
                    cell.value = ""
                cell.alignment = Alignment(wrap_text=True,vertical="top")
            sheet.row_dimensions[row_index].height = 48
            row_index += 1
        sheet.column_dimensions["A"].width = 16
        for col in range(2,last_col+1):
            sheet.column_dimensions[get_column_letter(col)].width = 22
        sheet.freeze_panes = "B6"
        sheet.sheet_view.showGridLines = False
        sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(last_col)}{row_index-1}"


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
            weekend.page_setup.orientation="landscape"; weekend.page_setup.paperSize=weekend.PAPERSIZE_A3
            weekend.page_setup.fitToWidth=1; weekend.page_setup.fitToHeight=1
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
        workbook.save(buffer)
        buffer.seek(0)
        filename = filename_prefix(school,result) + ".xlsx"
        return StreamingResponse(buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=" + filename})
