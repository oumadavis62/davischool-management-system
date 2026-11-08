"""Read-only timetable views for the whole school, classes, teachers and rooms."""
from __future__ import annotations

from html import escape

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.timetable.views import get_timetable_view
from app.timetable.setup import TimetableSetupError


def register_timetable_view_routes(app, get_db, get_school_obj, module_page):
    def school_for(request):
        if not request.session.get("email") or request.session.get("role") not in ("school_admin", "registrar", "super_admin"):
            return None
        return get_school_obj(request)

    @app.get("/app/timetable/views", response_class=HTMLResponse)
    def timetable_views_page(
        request: Request,
        profile_id: int = 0,
        view_type: str = "school",
        class_id: int = 0,
        teacher_id: int = 0,
        room_id: int = 0,
        message: str = "",
        remedial_display: str = "combined",
    ):
        school = school_for(request)
        if not school:
            return RedirectResponse("/", 303)
        school_id = int(school["id"])
        con = get_db()
        cur = con.cursor()
        profiles = cur.execute(
            "SELECT * FROM ds_timetable_profiles WHERE school_id=? ORDER BY academic_year DESC,term,id DESC",
            (school_id,),
        ).fetchall()
        selected = (next((p for p in profiles if int(p["id"]) == int(profile_id)), None) or (profiles[0] if profiles else None))
        classes = cur.execute("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream", (school_id,)).fetchall()
        teachers = cur.execute("SELECT id,name FROM teachers WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
        rooms = cur.execute("SELECT id,name,room_code FROM ds_timetable_rooms WHERE school_id=? AND is_active=1 ORDER BY name", (school_id,)).fetchall()
        con.close()

        esc = lambda value: escape(str(value if value is not None else ""))
        pid = int(selected["id"]) if selected else 0
        notice = f"<div class='tv-alert'>{esc(message)}</div>" if message else ""
        profile_options = "".join(
            f"<option value='{int(p['id'])}' {'selected' if selected and int(p['id'])==pid else ''}>{esc(p['academic_year'])} · {esc(p['term'])} — {esc(p['name'])}</option>"
            for p in profiles
        )
        class_options = "<option value='0'>Choose class / stream</option>" + "".join(
            f"<option value='{int(x['id'])}' {'selected' if int(x['id'])==int(class_id) else ''}>{esc(x['name'])} {esc(x['stream'] or '')}</option>"
            for x in classes
        )
        teacher_options = "<option value='0'>Choose teacher</option>" + "".join(
            f"<option value='{int(x['id'])}' {'selected' if int(x['id'])==int(teacher_id) else ''}>{esc(x['name'])}</option>"
            for x in teachers
        )
        room_options = "<option value='0'>Choose room</option>" + "".join(
            f"<option value='{int(x['id'])}' {'selected' if int(x['id'])==int(room_id) else ''}>{esc(x['name'])} ({esc(x['room_code'])})</option>"
            for x in rooms
        )
        result = None
        view_error = ""
        target_id = {"class":class_id,"teacher":teacher_id,"room":room_id}.get(view_type,0)
        if selected and (view_type == "school" or target_id):
            try:
                view_con = get_db()
                try:
                    result = get_timetable_view(view_con, school_id, pid, view_type, int(target_id))
                finally:
                    view_con.close()
            except TimetableSetupError as exc:
                view_error = str(exc)
        elif selected and view_type not in ("school","class","teacher","room"):
            view_error = "Choose a valid timetable view."
        elif selected and view_type != "school":
            view_error = "Choose the class, teacher or room you want to view."

        grid = "<div class='tv-empty'>Select a timetable profile and view type to display a schedule.</div>"
        lesson_count = 0
        if result:
            days = result["days"]
            periods = result["periods"]
            breaks = result.get("breaks", [])
            lessons = result["lessons"]
            lesson_count = len(lessons)
            period_index = {int(p["id"]):i for i,p in enumerate(periods)}
            by_start = {}
            occupied = {}
            for lesson in lessons:
                key = (int(lesson["day_id"]),int(lesson["period_id"]))
                by_start.setdefault(key,[]).append(lesson)
                start = period_index.get(int(lesson["period_id"]))
                if start is not None:
                    for offset in range(1,int(lesson["duration_periods"] or 1)):
                        if start + offset < len(periods):
                            occupied[(int(lesson["day_id"]),int(periods[start+offset]["id"]))] = lesson
            timeline = sorted(
                [(str(p["start_time"]), "period", p) for p in periods] +
                [(str(br["start_time"]), "break", br) for br in breaks],
                key=lambda item: (item[0], 0 if item[1] == "period" else 1),
            )
            headers = ["<th class='tv-day-heading'>Day</th>"]
            for _, item_type, item in timeline:
                if item_type == "break":
                    headers.append(
                        f"<th class='tv-break-heading'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></th>"
                    )
                else:
                    headers.append(
                        f"<th class='tv-period-heading'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></th>"
                    )
            rows = []
            for day in days:
                cells = [f"<th class='tv-day-heading'>{esc(day['day_name'])}</th>"]
                for _, item_type, item in timeline:
                    if item_type == "break":
                        cells.append(
                            f"<td class='tv-break-cell'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></td>"
                        )
                        continue
                    key = (int(day["id"]), int(item["id"]))
                    starts = by_start.get(key, [])
                    if starts:
                        cards = []
                        for lesson in starts:
                            class_name = esc(lesson["class_name"]) + ((" " + esc(lesson["stream"])) if lesson["stream"] else "")
                            cards.append(
                                f"<div class='tv-lesson'><b>{esc(lesson['subject_name'])}</b><span>{class_name}</span><small>{esc(lesson['teacher_name'])}</small><small>⌂ {esc(lesson['room_name'] or 'No room assigned')}</small></div>"
                            )
                        cells.append(f"<td class='tv-cell'>{''.join(cards)}</td>")
                    elif key in occupied:
                        cells.append(f"<td class='tv-cell tv-continued'>↳ {esc(occupied[key]['subject_name'])} continues</td>")
                    else:
                        cells.append("<td class='tv-cell tv-free'>—</td>")
                rows.append(f"<tr>{''.join(cells)}</tr>")
            grid = (
                "<div class='tv-grid-scroll'><table class='tv-grid'><thead><tr>"
                + "".join(headers)
                + "</tr></thead><tbody>"
                + "".join(rows)
                + "</tbody></table></div>"
            )

        view_error_html = f"<div class='tv-alert'>{esc(view_error)}</div>" if view_error else ""
        export_query = f"profile_id={pid}&view_type={view_type}&class_id={int(class_id)}&teacher_id={int(teacher_id)}&room_id={int(room_id)}&remedial_display={remedial_display}"
        summary_html = (
            f"<div class='tv-summary'><div><b>{esc(result['title'])}</b><br><span>{esc(selected['academic_year'])} · {esc(selected['term'])}</span></div><span>{lesson_count} scheduled lessons</span></div>"
            if result else ""
        )
        remedial_display = "separate" if remedial_display == "separate" else "combined"
        def session_table(items, include_rotation=False):
            if not items:
                return "<div class='tv-session-empty'>No sessions scheduled in this section.</div>"
            headers = (["Weekend rotation"] if include_rotation else []) + ["Date / Day","Time","Lesson / Activity","Class / Group","Teacher(s)","Venue"]
            rows = []
            for item in items:
                date_label = str(item.get("session_date") or item.get("day_name") or "Weekly")
                if item.get("session_date") and item.get("day_name"):
                    date_label += " · " + str(item["day_name"])
                values = ([item.get("rotation_label") or "Weekend rotation"] if include_rotation else []) + [
                    date_label, str(item["start_time"]) + "–" + str(item["end_time"]),
                    str(item.get("subject_name") or item.get("programme_name") or item.get("session_type") or "Session"),
                    str(item.get("class_names") or "—"), str(item.get("teacher_names") or "—"),
                    str(item.get("room_name") or "—"),
                ]
                rows.append("<tr>" + "".join("<td>" + esc(value) + "</td>" for value in values) + "</tr>")
            return "<div class='tv-session-scroll'><table class='tv-session-table'><thead><tr>" + "".join("<th>"+esc(h)+"</th>" for h in headers) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        weekday_remedial_html = ""
        if result and result.get("weekday_remedials"):
            weekday_remedial_html = "<section class='tv-extra-section " + ("tv-remedial-separate" if remedial_display == "separate" else "tv-remedial-combined") + "'><div class='tv-extra-title'><h3>Weekday remedial & study sessions</h3><span>" + ("Separate remedial sheet" if remedial_display == "separate" else "Included with normal weekly timetable") + "</span></div>" + session_table(result["weekday_remedials"]) + "</section>"
        weekend_html = ""
        if result and result.get("weekend_sessions"):
            weekend_html = "<section class='tv-extra-section tv-weekend-sheet'><div class='tv-extra-title'><h3>Weekend lessons & remedials</h3><span>All weekend rotations consolidated on one sheet</span></div>" + session_table(result["weekend_sessions"], True) + "</section>"

        body = f"""
        <style>
        .tv-wrap{{max-width:1600px;margin:auto;padding:20px;color:#173d2b}}.tv-hero{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}}.tv-hero h2{{font-size:25px;margin:3px 0 5px}}.tv-hero p{{font-size:12px;color:#64748b;margin:0}}.tv-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}.tv-actions{{display:flex;gap:8px;flex-wrap:wrap}}.tv-btn{{display:inline-flex;padding:10px 14px;border:0;border-radius:9px;background:#17633b;color:white;text-decoration:none;font-size:12px;font-weight:800;cursor:pointer}}.tv-btn.secondary{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8}}.tv-filter{{display:grid;grid-template-columns:1.2fr 1fr 1fr 1fr auto;gap:10px;align-items:end;background:white;border:1px solid #e1ebe3;border-radius:14px;padding:15px;margin-bottom:15px}}.tv-filter label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:#334155}}.tv-filter select{{padding:10px;border:1px solid #dce7de;border-radius:9px;background:white;min-width:0;font-size:12px}}.tv-summary{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;background:white;border:1px solid #e1ebe3;border-radius:12px;padding:13px 15px;margin-bottom:14px}}.tv-extra-section{{margin-top:18px;background:#fff;border:1px solid #dce7de;border-radius:13px;padding:14px;break-inside:avoid}}.tv-extra-title{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}}.tv-extra-title h3{{margin:0;font-size:16px;color:#1d563b}}.tv-extra-title span{{font-size:10px;color:#647b6a}}.tv-session-scroll{{overflow:auto}}.tv-session-table{{width:100%;border-collapse:collapse;font-size:11px}}.tv-session-table th{{background:#17633b;color:white;text-align:left;padding:8px}}.tv-session-table td{{padding:7px;border-bottom:1px solid #e4ece5}}.tv-session-empty{{padding:10px;color:#64748b;font-size:11px}}.tv-weekend-sheet{{border:2px solid #b8d2bd}}.tv-remedial-separate{{background:#f8fbf8}}.tv-summary b{{font-size:16px}}.tv-summary span{{font-size:11px;color:#64748b}}.tv-grid-scroll{{overflow:auto;border:1px solid #dce7de;border-radius:13px;background:white}}.tv-grid{{width:100%;border-collapse:separate;border-spacing:0;min-width:850px}}.tv-grid thead th{{background:#17633b;color:white;padding:13px 10px;text-align:center;font-size:12px;position:sticky;top:0;min-width:135px}}.tv-grid .tv-day-heading{{min-width:115px;background:#f0f6f1;color:#315b3e;text-align:left;position:sticky;left:0;z-index:2}}.tv-day-heading b,.tv-day-heading span,.tv-period-heading b,.tv-period-heading span,.tv-break-heading b,.tv-break-heading span{{display:block}}.tv-period-heading span,.tv-break-heading span{{font-size:10px;color:#e0eee3;font-weight:600;margin-top:4px}}.tv-break-heading,.tv-break-cell{{background:#f1ead8!important;color:#75551d;text-align:center;min-width:115px;padding:10px 8px;border-bottom:1px solid #e5d8b9}}.tv-break-heading span{{color:#75551d}}.tv-break-cell span{{display:block;font-size:10px;margin-top:4px}}.tv-break-row td{{border-bottom:1px solid #e5d8b9}}.tv-cell{{height:104px;min-width:145px;vertical-align:top;padding:6px;border-right:1px solid #edf2ed;border-bottom:1px solid #edf2ed}}.tv-lesson{{background:#eaf5ec;border-left:3px solid #287447;border-radius:8px;padding:7px;margin-bottom:5px;font-size:10px;color:#173d2b}}.tv-lesson b,.tv-lesson span,.tv-lesson small{{display:block}}.tv-lesson span{{font-weight:800;margin-top:4px}}.tv-lesson small{{font-size:9px;color:#55705d;margin-top:3px}}.tv-free{{text-align:center;vertical-align:middle;color:#c0ccc1;font-size:12px}}.tv-continued{{text-align:center;vertical-align:middle;background:#f6faf6;color:#7b9480;font-size:10px}}.tv-alert{{padding:11px 14px;background:#fff7e8;color:#8b5b14;border-radius:9px;margin-bottom:12px;font-size:12px}}.tv-empty{{padding:30px;text-align:center;color:#64748b;background:white;border:1px dashed #cdddcf;border-radius:12px}}@media(max-width:900px){{.tv-filter{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:600px){{.tv-wrap{{padding:12px}}.tv-filter{{grid-template-columns:1fr}}.tv-hero h2{{font-size:22px}}}}@page weekend-sheet{{size:A3 landscape;margin:10mm}}@media print{{.tv-hero .tv-actions,.tv-filter,.tv-alert{{display:none!important}}.tv-remedial-separate{{break-before:page}}.tv-weekend-sheet{{page:weekend-sheet;break-before:page}}.tv-session-scroll{{overflow:visible}}.tv-session-table{{font-size:9px}}.tv-wrap{{padding:0;max-width:none}}.tv-grid-scroll{{overflow:visible;border:1px solid #999}}.tv-grid{{min-width:0}}.tv-grid thead th{{position:static;background:#eaf5ec!important;color:#173d2b!important}}.tv-cell{{height:auto;min-width:0}}}}
        </style>
        <div class='tv-wrap'><div class='tv-hero'><div><span class='tv-kicker'>DAVISCHOOL · TIMETABLE VIEWS</span><h2>Timetable Views</h2><p>Inspect the published or draft timetable by school, class, teacher or room.</p></div><div class='tv-actions'><a class='tv-btn secondary' href='/app/timetable/export/pdf?{export_query}'>Export PDF</a><a class='tv-btn secondary' href='/app/timetable/export/xlsx?{export_query}'>Export Excel</a><button class='tv-btn' onclick='window.print()'>Print view</button><a class='tv-btn secondary' href='/app/timetable/builder?profile_id={pid}'>Master Builder</a><a class='tv-btn secondary' href='/app/timetable/automatic?profile_id={pid}'>Automatic Generator</a><a class='tv-btn secondary' href='/app/timetable/publishing?profile_id={pid}'>Publishing & Versions</a></div></div>{notice}
        <form method='get' action='/app/timetable/views' class='tv-filter'><label>Academic timetable<select name='profile_id'>{profile_options}</select></label><label>View type<select name='view_type'><option value='school' {'selected' if view_type=='school' else ''}>Whole school</option><option value='class' {'selected' if view_type=='class' else ''}>Class / stream</option><option value='teacher' {'selected' if view_type=='teacher' else ''}>Teacher</option><option value='room' {'selected' if view_type=='room' else ''}>Room / facility</option></select></label><label>Class / stream<select name='class_id'>{class_options}</select></label><label>Teacher<select name='teacher_id'>{teacher_options}</select></label><label>Room<select name='room_id'>{room_options}</select></label><label>Weekday remedials<select name='remedial_display'><option value='combined' {'selected' if remedial_display=='combined' else ''}>Same sheet as normal lessons</option><option value='separate' {'selected' if remedial_display=='separate' else ''}>Separate remedial sheet</option></select></label><button class='tv-btn'>View timetable</button></form>
        {view_error_html}
        {summary_html}
        {grid}
        {weekday_remedial_html}
        {weekend_html}
        </div>
        """
        return module_page(request, "Timetable Views", "timetable", body)
