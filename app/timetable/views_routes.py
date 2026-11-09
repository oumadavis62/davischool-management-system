"""Read-only timetable views for the whole school, classes, teachers and rooms."""
from __future__ import annotations

from html import escape

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.timetable.views import get_timetable_view
from app.timetable.setup import TimetableSetupError


def register_timetable_view_routes(app, get_db, get_school_obj, module_page):
    from app.timetable.navigation import timetable_workspace
    _base_module_page = module_page
    def module_page(request, title, module, body):
        return _base_module_page(request, title, module, timetable_workspace(request, body))
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
            period_index = {int(p["id"]): i for i, p in enumerate(periods)}
            timeline = sorted(
                [(str(p["start_time"]), "period", p) for p in periods] +
                [(str(br["start_time"]), "break", br) for br in breaks],
                key=lambda item: (item[0], 0 if item[1] == "period" else 1),
            )
            class_map = {}
            for lesson in lessons:
                key = (str(lesson["class_name"]), str(lesson["stream"] or ""))
                class_map[key] = key
            if view_type == "class" and result.get("target"):
                target = result["target"]
                class_map = {(str(target["name"]), str(target["stream"] or "")): (str(target["name"]), str(target["stream"] or ""))}
            class_rows = sorted(class_map.values(), key=lambda item: (item[0].casefold(), item[1].casefold()))
            if not class_rows:
                class_rows = [("", "")]
            headers = ["<th class='tb-day-heading'>Day</th>", "<th class='tb-class-heading'>Class / Stream</th>"]
            for _, item_type, item in timeline:
                if item_type == "break":
                    headers.append(f"<th class='tb-break-heading'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></th>")
                else:
                    headers.append(f"<th class='tb-period-heading'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></th>")
            rows = []
            for day in days:
                day_rows = class_rows
                for class_index, (class_name, stream_name) in enumerate(day_rows):
                    cells = []
                    if class_index == 0:
                        cells.append(f"<th class='tb-day-heading' rowspan='{len(day_rows)}'>{esc(day['day_name'])}</th>")
                    class_label = f"<b class='tb-class-name'>{esc(class_name)}</b>" if class_name else "<b class='tb-class-name'>—</b>"
                    stream_label = f"<span class='tb-stream-name'>{esc(stream_name)}</span>" if stream_name else ""
                    cells.append(f"<th class='tb-class-heading'>{class_label}{stream_label}</th>")
                    for _, item_type, item in timeline:
                        if item_type == "break":
                            cells.append(f"<td class='tb-break-cell'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></td>")
                            continue
                        matching = [
                            lesson for lesson in lessons
                            if int(lesson["day_id"]) == int(day["id"])
                            and int(lesson["period_id"]) == int(item["id"])
                            and str(lesson["class_name"]) == class_name
                            and str(lesson["stream"] or "") == stream_name
                        ]
                        if matching:
                            cards = []
                            for lesson in matching:
                                duration = max(1, int(lesson["duration_periods"] or 1))
                                subject_parts = [part for part in str(lesson["subject_name"] or "").split() if part]
                                subject_initial = "".join(part[0] for part in subject_parts[:3]).upper() or "—"
                                teacher_parts = [part for part in str(lesson["teacher_name"] or "").split() if part]
                                teacher_initials = "".join(part[0] for part in (teacher_parts[:1] + (teacher_parts[-1:] if len(teacher_parts) > 1 else []))).upper()[:4] or "—"
                                cards.append(
                                    f"<div class='tb-lesson' style='--teacher-color:#287447' title='{esc(lesson['subject_name'])} · {esc(lesson['teacher_name'])}'>"
                                    f"<div class='tb-lesson-top'><b class='tb-subject-initials'>{esc(subject_initial)}</b><span>{duration}P</span></div>"
                                    f"<div class='tb-meta tb-room-label'>⌂ {esc(lesson['room_name'] or 'No room assigned')}</div>"
                                    f"<div class='tb-lesson-footer'><span class='tb-teacher-initials' title='{esc(lesson['teacher_name'])}'>{esc(teacher_initials)}</span></div></div>"
                                )
                            cells.append(f"<td class='tb-cell tb-cell-multi'>{''.join(cards)}</td>")
                        else:
                            cells.append("<td class='tb-cell tb-free'><span>Free period</span></td>")
                    row_class = " class='tb-day-end'" if class_index == len(day_rows) - 1 else ""
                    rows.append(f"<tr{row_class}>{''.join(cells)}</tr>")
            grid = "<div class='tb-grid-scroll'><table class='tb-grid'><thead><tr>" + "".join(headers) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
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
        dated_instructional_html = ""
        if result and result.get("dated_instructional_sessions"):
            dated_instructional_html = "<section class='tv-extra-section tv-dated-instructional'><div class='tv-extra-title'><h3>Calendar-dated instructional lessons</h3><span>Generated sessions shown by their actual dates</span></div>" + session_table(result["dated_instructional_sessions"]) + "</section>"
        weekday_remedial_html = ""
        if result and result.get("weekday_remedials"):
            weekday_remedial_html = "<section class='tv-extra-section " + ("tv-remedial-separate" if remedial_display == "separate" else "tv-remedial-combined") + "'><div class='tv-extra-title'><h3>Weekday remedial & study sessions</h3><span>" + ("Separate remedial sheet" if remedial_display == "separate" else "Included with normal weekly timetable") + "</span></div>" + session_table(result["weekday_remedials"]) + "</section>"
        weekend_html = ""
        if result and result.get("weekend_sessions"):
            weekend_html = "<section class='tv-extra-section tv-weekend-sheet'><div class='tv-extra-title'><h3>Weekend lessons & remedials</h3><span>All weekend rotations consolidated on one sheet</span></div>" + session_table(result["weekend_sessions"], True) + "</section>"

        body = f"""
        <style>
        .tv-wrap{{max-width:1600px;margin:auto;padding:20px;color:#173d2b}}.tv-hero{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}}.tv-hero h2{{font-size:25px;margin:3px 0 5px}}.tv-hero p{{font-size:12px;color:#64748b;margin:0}}.tv-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}.tv-actions{{display:flex;gap:8px;flex-wrap:wrap}}.tv-btn{{display:inline-flex;padding:10px 14px;border:0;border-radius:9px;background:#17633b;color:white;text-decoration:none;font-size:12px;font-weight:800;cursor:pointer}}.tv-btn.secondary{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8}}.tv-filter{{display:grid;grid-template-columns:1.2fr 1fr 1fr 1fr auto;gap:10px;align-items:end;background:white;border:1px solid #e1ebe3;border-radius:14px;padding:15px;margin-bottom:15px}}.tv-filter label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:#334155}}.tv-filter select{{padding:10px;border:1px solid #dce7de;border-radius:9px;background:white;min-width:0;font-size:12px}}.tv-summary{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;background:white;border:1px solid #e1ebe3;border-radius:12px;padding:13px 15px;margin-bottom:14px}}.tv-extra-section{{margin-top:18px;background:#fff;border:1px solid #dce7de;border-radius:13px;padding:14px;break-inside:avoid}}.tv-extra-title{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}}.tv-extra-title h3{{margin:0;font-size:16px;color:#1d563b}}.tv-extra-title span{{font-size:10px;color:#647b6a}}.tv-session-scroll{{overflow:auto}}.tv-session-table{{width:100%;border-collapse:collapse;font-size:11px}}.tv-session-table th{{background:#17633b;color:white;text-align:left;padding:8px}}.tv-session-table td{{padding:7px;border-bottom:1px solid #e4ece5}}.tv-session-empty{{padding:10px;color:#64748b;font-size:11px}}.tv-weekend-sheet{{border:2px solid #b8d2bd}}.tv-remedial-separate{{background:#f8fbf8}}.tv-summary b{{font-size:16px}}.tv-summary span{{font-size:11px;color:#64748b}}.tv-dialog{{border:0;border-radius:16px;padding:0;width:min(560px,calc(100% - 24px));max-width:560px;box-shadow:0 22px 70px rgba(20,55,32,.28)}}.tv-dialog::backdrop{{background:rgba(17,38,24,.48);backdrop-filter:blur(3px)}}.tv-dialog .tv-filter{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;background:#fff;border:0;border-radius:16px;padding:18px;margin:0}}.tv-dialog-head{{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}}.tv-dialog-head b,.tv-dialog-head span{{display:block}}.tv-dialog-head b{{font-size:16px;color:#1d563b}}.tv-dialog-head span{{font-size:11px;color:#718276;margin-top:4px}}.tv-close{{border:0;background:#edf5ee;color:#285d3a;border-radius:9px;width:34px;height:34px;font-size:22px;cursor:pointer}}.tv-dialog-actions{{grid-column:1/-1;display:flex;justify-content:flex-end;gap:8px;margin-top:5px}}.tv-export-content{{display:grid;gap:10px;padding:18px}}.tv-export-content>.tv-btn{{justify-content:center}}.tv-view-actions{{margin:0 0 12px}}.tv-grid-scroll{{overflow:auto;border:1px solid #dce8de;border-radius:15px;background:white;box-shadow:0 6px 20px rgba(36,83,52,.045)}}.tv-grid{{width:100%;border-collapse:separate;border-spacing:0;min-width:995px}}.tv-grid thead th{{background:linear-gradient(110deg,#347b50,#286743);color:white;padding:8px 7px;text-align:center;font-size:12px;position:sticky;top:0;min-width:135px;border-bottom:5px solid #b7d1bc!important}}.tv-grid thead th.tb-period-heading{{border-right:2px solid #8eaf95!important}}.tv-grid .tb-day-heading{{min-width:115px;background:#edf5ee;color:#315b3e;text-align:center;vertical-align:middle;position:sticky;left:0;z-index:2}}.tv-grid .tb-class-heading{{width:76px;min-width:76px;max-width:76px;box-sizing:border-box;padding:6px 4px;background:#f5f9f5;color:#315b3e;text-align:center;vertical-align:middle;position:sticky;left:115px;z-index:1;font-size:9px;line-height:1.15;overflow-wrap:anywhere}}.tv-grid .tb-class-name,.tv-grid .tb-stream-name{{display:block}}.tv-grid .tb-class-name{{font-size:9px;font-weight:800}}.tv-grid .tb-stream-name{{margin-top:2px;color:#64816a;font-size:8px;font-weight:700}}.tv-grid .tb-period-heading b,.tv-grid .tb-period-heading span,.tv-grid .tb-break-heading b,.tv-grid .tb-break-heading span{{display:block}}.tv-grid tbody tr>th,.tv-grid tbody tr>td{{border-bottom:2px solid #c7d9ca!important}}.tv-grid tbody tr.tb-day-end>th,.tv-grid tbody tr.tb-day-end>td{{border-bottom:5px solid #6f9b78!important}}.tv-grid tbody .tb-day-heading{{vertical-align:middle;text-align:center;white-space:nowrap;box-shadow:inset 0 -3px 0 #6f9b78}}.tv-grid .tb-break-heading,.tv-grid .tb-break-cell{{background:#f1ead8!important;color:#75551d;text-align:center;min-width:115px;padding:10px 8px}}.tv-grid .tb-break-heading span{{color:#75551d}}.tv-grid .tb-break-cell span{{display:block;font-size:10px;margin-top:4px}}.tv-grid .tb-cell{{height:82px;min-width:125px;vertical-align:middle;text-align:center;padding:4px;border-right:2px solid #b4cbb8;border-bottom:1px solid #edf2ed;background:#fff}}.tv-grid .tb-cell-multi{{height:82px;vertical-align:middle;text-align:center}}.tv-grid .tb-free{{background:#fbfdfb;text-align:center;vertical-align:middle;color:#a2b3a5;font-size:10px}}.tv-grid .tb-lesson{{--teacher-color:#287447;position:relative;box-sizing:border-box;background:color-mix(in srgb,var(--teacher-color) 17%,white);border:1px solid color-mix(in srgb,var(--teacher-color) 48%,white);border-left:4px solid var(--teacher-color);border-radius:8px;padding:5px 7px;min-height:66px;color:#234638;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;text-align:center;gap:2px;box-shadow:0 2px 7px rgba(35,83,51,.07)}}.tv-grid .tb-lesson-top{{display:flex;justify-content:center;align-items:center;gap:9px;font-size:10px;width:100%}}.tv-grid .tb-lesson-top span{{position:absolute;top:4px;right:5px;font-size:9px;background:#d5e9d9;border-radius:10px;padding:2px 5px}}.tv-grid .tb-subject-initials{{font-size:12px;letter-spacing:.5px;font-weight:900}}.tv-grid .tb-meta{{font-size:8px;color:#55705d;margin-top:2px}}.tv-grid .tb-room-label{{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.tv-grid .tb-lesson-footer{{display:flex;align-items:center;justify-content:flex-end;width:100%;min-height:14px;margin-top:auto}}.tv-grid .tb-teacher-initials{{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:16px;padding:0 4px;border-radius:5px;background:#245b39;color:#fff;font-size:8px;font-weight:950}}.tv-grid{{width:100%;border-collapse:separate;border-spacing:0;min-width:850px}}.tv-grid thead th{{background:#17633b;color:white;padding:13px 10px;text-align:center;font-size:12px;position:sticky;top:0;min-width:135px}}.tv-grid .tv-day-heading{{min-width:115px;background:#f0f6f1;color:#315b3e;text-align:left;position:sticky;left:0;z-index:2}}.tv-day-heading b,.tv-day-heading span,.tv-period-heading b,.tv-period-heading span,.tv-break-heading b,.tv-break-heading span{{display:block}}.tv-period-heading span,.tv-break-heading span{{font-size:10px;color:#e0eee3;font-weight:600;margin-top:4px}}.tv-break-heading,.tv-break-cell{{background:#f1ead8!important;color:#75551d;text-align:center;min-width:115px;padding:10px 8px;border-bottom:1px solid #e5d8b9}}.tv-break-heading span{{color:#75551d}}.tv-break-cell span{{display:block;font-size:10px;margin-top:4px}}.tv-break-row td{{border-bottom:1px solid #e5d8b9}}.tv-cell{{height:104px;min-width:145px;vertical-align:top;padding:6px;border-right:1px solid #edf2ed;border-bottom:1px solid #edf2ed}}.tv-lesson{{background:#eaf5ec;border-left:3px solid #287447;border-radius:8px;padding:7px;margin-bottom:5px;font-size:10px;color:#173d2b}}.tv-lesson b,.tv-lesson span,.tv-lesson small{{display:block}}.tv-lesson span{{font-weight:800;margin-top:4px}}.tv-lesson small{{font-size:9px;color:#55705d;margin-top:3px}}.tv-free{{text-align:center;vertical-align:middle;color:#c0ccc1;font-size:12px}}.tv-continued{{text-align:center;vertical-align:middle;background:#f6faf6;color:#7b9480;font-size:10px}}.tv-alert{{padding:11px 14px;background:#fff7e8;color:#8b5b14;border-radius:9px;margin-bottom:12px;font-size:12px}}.tv-empty{{padding:30px;text-align:center;color:#64748b;background:white;border:1px dashed #cdddcf;border-radius:12px}}@media(max-width:900px){{.tv-filter{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:600px){{.tv-wrap{{padding:12px}}.tv-dialog .tv-filter{{grid-template-columns:1fr}}.tv-hero h2{{font-size:22px}}}}@page{{size:A4 landscape;margin:8mm}}@media print{{.tv-hero .tv-actions,.tv-filter,.tv-alert{{display:none!important}}.tv-remedial-separate{{break-before:page}}.tv-weekend-sheet{{break-before:page}}.tv-session-scroll{{overflow:visible}}.tv-session-table{{font-size:9px}}.tv-wrap{{padding:0;max-width:none}}.tv-grid-scroll{{overflow:visible;border:1px solid #999}}.tv-grid{{min-width:0}}.tv-grid thead th{{position:static;background:#eaf5ec!important;color:#173d2b!important}}.tv-cell{{height:auto;min-width:0}}}}
        </style>
        <div class='tv-wrap'><div class='tv-hero'><div><span class='tv-kicker'>DAVISCHOOL · TIMETABLE VIEWS</span><h2>Timetable Views</h2><p>Inspect the published or draft timetable by school, class, teacher or room.</p></div><div class='tv-actions'><a class='tv-btn secondary' href='/app/timetable/export/pdf?{export_query}'>Export PDF</a><a class='tv-btn secondary' href='/app/timetable/export/xlsx?{export_query}'>Export Excel</a><button class='tv-btn' onclick='window.print()'>Print view</button><a class='tv-btn secondary' href='/app/timetable/builder?profile_id={pid}'>Master Builder</a><a class='tv-btn secondary' href='/app/timetable/automatic?profile_id={pid}'>Automatic Generator</a><a class='tv-btn secondary' href='/app/timetable/publishing?profile_id={pid}'>Publishing & Versions</a></div></div>{notice}
        <div class='tv-actions tv-view-actions'><button type='button' class='tv-btn' onclick="document.getElementById('tv-filter-dialog').showModal()">Choose timetable view</button><button type='button' class='tv-btn secondary' onclick="document.getElementById('tv-export-dialog').showModal()">Export / print</button></div>
        <dialog id='tv-filter-dialog' class='tv-dialog'><form method='get' action='/app/timetable/views' class='tv-filter'><div class='tv-dialog-head'><div><b>Timetable view settings</b><span>Select the timetable and the group to display</span></div><button type='button' class='tv-close' onclick="this.closest('dialog').close()">×</button></div><label>Academic timetable<select name='profile_id'>{profile_options}</select></label><label>View type<select name='view_type'><option value='school' {'selected' if view_type=='school' else ''}>Whole school</option><option value='class' {'selected' if view_type=='class' else ''}>Class / stream</option><option value='teacher' {'selected' if view_type=='teacher' else ''}>Teacher</option><option value='room' {'selected' if view_type=='room' else ''}>Room / facility</option></select></label><label>Class / stream<select name='class_id'>{class_options}</select></label><label>Teacher<select name='teacher_id'>{teacher_options}</select></label><label>Room<select name='room_id'>{room_options}</select></label><label>Weekday remedials<select name='remedial_display'><option value='combined' {'selected' if remedial_display=='combined' else ''}>Same sheet as normal lessons</option><option value='separate' {'selected' if remedial_display=='separate' else ''}>Separate remedial sheet</option></select></label><div class='tv-dialog-actions'><button type='button' class='tv-btn secondary' onclick="this.closest('dialog').close()">Cancel</button><button class='tv-btn'>Apply view</button></div></form></dialog>
        <dialog id='tv-export-dialog' class='tv-dialog'><div class='tv-export-content'><div class='tv-dialog-head'><div><b>Export timetable</b><span>Choose how to use the displayed timetable</span></div><button type='button' class='tv-close' onclick="this.closest('dialog').close()">×</button></div><a class='tv-btn secondary' href='/app/timetable/export/pdf?{export_query}'>Export PDF</a><a class='tv-btn secondary' href='/app/timetable/export/xlsx?{export_query}'>Export Excel</a><button class='tv-btn' onclick="window.print()">Print timetable</button></div></dialog>
        {view_error_html}
        {summary_html}
        {grid}
        {dated_instructional_html}
        {weekday_remedial_html}
        {weekend_html}
        </div>
        """
        return module_page(request, "Timetable Views", "timetable", body)
