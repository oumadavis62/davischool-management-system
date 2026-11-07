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
    ):
        school, result, error = load_view(request, profile_id, view_type, class_id, teacher_id, room_id)
        if error:
            return error
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)
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
        headers = [Paragraph("Period", header_style), Paragraph("Time", header_style)] + [Paragraph(pdf_text(str(d["day_name"])), header_style) for d in result["days"]]
        data = [headers]
        for period in result["periods"]:
            row = [Paragraph(pdf_text(str(period["label"])), cell_style), Paragraph(pdf_text(str(period["start_time"])) + " - " + pdf_text(str(period["end_time"])), cell_style)]
            for day in result["days"]:
                key = (int(day["id"]),int(period["id"]))
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
        first_width = 65
        time_width = 75
        day_width = max(70,(available_width-first_width-time_width)/max(1,len(result["days"])))
        table = Table(data, colWidths=[first_width,time_width]+[day_width]*len(result["days"]), repeatRows=1)
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
        story.append(table)
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
    ):
        school, result, error = load_view(request, profile_id, view_type, class_id, teacher_id, room_id)
        if error:
            return error
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        buffer = BytesIO()
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Timetable"
        last_col = 2 + len(result["days"])
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
        headers = ["Period","Time"] + [str(d["day_name"]) for d in result["days"]]
        for col, value in enumerate(headers,1):
            cell = sheet.cell(header_row,col,value)
            cell.font = Font(bold=True,color="FFFFFF")
            cell.fill = PatternFill("solid",fgColor="17633B")
            cell.alignment = Alignment(horizontal="center",vertical="center")
        starts, continued = cell_map(result)
        for row_index, period in enumerate(result["periods"],header_row+1):
            sheet.cell(row_index,1,str(period["label"]))
            sheet.cell(row_index,2,str(period["start_time"])+"–"+str(period["end_time"]))
            for col, day in enumerate(result["days"],3):
                key = (int(day["id"]),int(period["id"]))
                if key in starts:
                    lines = []
                    for lesson in starts[key]:
                        class_label = str(lesson["class_name"]) + ((" " + str(lesson["stream"])) if lesson["stream"] else "")
                        lines.append(str(lesson["subject_name"]) + " — " + class_label + "\n" + str(lesson["teacher_name"]) + "\n" + str(lesson["room_name"] or "No room"))
                    value = "\n\n".join(lines)
                elif key in continued:
                    value = "↳ " + str(continued[key]["subject_name"]) + " continues"
                else:
                    value = ""
                sheet.cell(row_index,col,value).alignment = Alignment(wrap_text=True,vertical="top")
            sheet.row_dimensions[row_index].height = 48
        sheet.column_dimensions["A"].width = 16
        sheet.column_dimensions["B"].width = 18
        for col in range(3,last_col+1):
            sheet.column_dimensions[chr(64+col)].width = 24
        sheet.freeze_panes = "C6"
        sheet.sheet_view.showGridLines = False
        sheet.auto_filter.ref = f"A{header_row}:{chr(64+last_col)}{header_row+len(result['periods'])}"

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
