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
            # Count occupied teaching periods, not lesson blocks: a double lesson
            # contributes two scheduled periods and a triple contributes three.
            lesson_count = sum(int(lesson.get("duration_periods") or 1) for lesson in lessons)
            period_index = {int(p["id"]): i for i, p in enumerate(periods)}
            timeline = sorted(
                [(str(p["start_time"]), "period", p) for p in periods] +
                [(str(br["start_time"]), "break", br) for br in breaks],
                key=lambda item: (item[0], 0 if item[1] == "period" else 1),
            )
            # Match the builder's row set: all configured class/stream allocations
            # for a whole-school view, and only the selected classes for filtered views.
            class_rows_by_id = {}
            if view_type == "school":
                for row in result.get("allocation_classes", []):
                    class_rows_by_id[int(row["class_id"])] = {
                        "class_id": int(row["class_id"]),
                        "class_name": str(row["class_name"]),
                        "stream": str(row["stream"] or ""),
                    }
            for lesson in lessons:
                class_rows_by_id.setdefault(int(lesson["class_id"]), {
                    "class_id": int(lesson["class_id"]),
                    "class_name": str(lesson["class_name"]),
                    "stream": str(lesson["stream"] or ""),
                })
            if view_type == "class" and result.get("target"):
                target = result["target"]
                class_rows_by_id = {int(target["id"]): {
                    "class_id": int(target["id"]), "class_name": str(target["name"]),
                    "stream": str(target["stream"] or ""),
                }}
            class_rows = sorted(class_rows_by_id.values(), key=lambda item: (
                item["class_name"].casefold(), item["stream"].casefold()
            ))
            if view_type in ("teacher", "room"):
                # Like the teacher sheet, room view has one row per day;
                # each lesson card identifies its class and stream.
                class_rows = [{"class_id": 0, "class_name": "", "stream": ""}]
            if not class_rows:
                class_rows = [{"class_id": 0, "class_name": "—", "stream": ""}]
            lesson_by_start = {}
            for lesson in lessons:
                lesson_by_start.setdefault(
                    (int(lesson["day_id"]), int(lesson["class_id"]), int(lesson["period_id"])), []
                ).append(lesson)
            occupied = {}
            for lesson in lessons:
                start_index = period_index.get(int(lesson["period_id"]))
                if start_index is None:
                    continue
                for offset in range(1, max(1, int(lesson["duration_periods"] or 1))):
                    if start_index + offset < len(periods):
                        occupied.setdefault(
                            (int(lesson["day_id"]), int(lesson["class_id"]), int(periods[start_index + offset]["id"])), []
                        ).append(lesson)
            timeline_period_positions = {
                int(item["id"]): position
                for position, (_, item_type, item) in enumerate(timeline)
                if item_type == "period"
            }
            show_class_column = view_type == "school"
            headers = ["<th class='tb-day-heading'>Day</th>"]
            if show_class_column:
                headers.append("<th class='tb-class-heading'>Class / Stream</th>")
            for _, item_type, item in timeline:
                if item_type == "break":
                    headers.append(f"<th class='tb-break-heading' aria-label='{esc(item['label'])}'>{esc(item['start_time'])}–{esc(item['end_time'])}</th>")
                else:
                    headers.append(f"<th class='tb-period-heading'><b>{esc(item['label'])}</b><span>{esc(item['start_time'])}–{esc(item['end_time'])}</span></th>")
            rows = []
            for day_index, day in enumerate(days):
                day_class_rows = class_rows
                for class_index, class_row in enumerate(day_class_rows):
                    cells = []
                    if class_index == 0:
                        cells.append(f"<th class='tb-day-heading' rowspan='{len(day_class_rows)}'>{esc(day['day_name'])}</th>")
                    if show_class_column:
                        class_name_html = f"<b class='tb-class-name'>{esc(class_row['class_name'])}</b>"
                        stream_html = f"<span class='tb-stream-name'>{esc(class_row['stream'])}</span>" if class_row["stream"] else ""
                        cells.append(f"<th class='tb-class-heading'>{class_name_html}{stream_html}</th>")
                    merged_period_ids = set()
                    for timeline_position, (_, item_type, item) in enumerate(timeline):
                        if item_type == "break":
                            # Class and teacher views have one row per day:
                            # merge each break vertically across the full
                            # Monday-Friday timetable, not separately per day.
                            if day_index == 0 and class_index == 0:
                                # One break-name cell spans every displayed weekday
                                # row (and every class row in the whole-school view).
                                break_rowspan = len(days) * (len(class_rows) if view_type == "school" else 1)
                                cells.append(f"<td class='tb-break-cell tb-week-break' rowspan='{break_rowspan}'><span>{''.join('<i>' + ('&nbsp;' if ch.isspace() else esc(ch)) + '</i>' for ch in str(item['label']))}</span></td>")
                            continue
                        period = item
                        if int(period["id"]) in merged_period_ids:
                            continue
                        key = (int(day["id"]), int(class_row["class_id"]), int(period["id"]))
                        if view_type in ("teacher", "room"):
                            # Teacher and room sheets share one row per day;
                            # aggregate the selected resource's lessons across classes.
                            slot_lessons = [lesson for lesson in lessons if int(lesson["day_id"]) == int(day["id"]) and int(lesson["period_id"]) == int(period["id"])]
                            continued_lessons = [lesson for lesson in lessons if int(lesson["day_id"]) == int(day["id"]) and (int(day["id"]), int(lesson["class_id"]), int(period["id"])) in occupied and lesson in occupied[(int(day["id"]), int(lesson["class_id"]), int(period["id"]))]]
                        else:
                            slot_lessons = lesson_by_start.get(key, [])
                            continued_lessons = occupied.get(key, [])
                        if slot_lessons:
                            cards = []
                            cell_span = 1
                            for lesson in slot_lessons:
                                duration = max(1, int(lesson["duration_periods"] or 1))
                                start_period_index = period_index.get(int(lesson["period_id"]))
                                span_periods = [
                                    periods[start_period_index + offset]
                                    for offset in range(duration)
                                    if start_period_index is not None and start_period_index + offset < len(periods)
                                ]
                                can_merge = (
                                    len(span_periods) == duration
                                    and all(
                                        timeline_period_positions.get(int(span_periods[offset]["id"])) == timeline_position + offset
                                        for offset in range(duration)
                                    )
                                )
                                if can_merge and duration > cell_span:
                                    cell_span = duration
                                    merged_period_ids.update(int(p["id"]) for p in span_periods[1:])
                                teacher_color = str(lesson["teacher_color"] or "").strip()
                                if not (len(teacher_color) == 7 and teacher_color.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in teacher_color[1:])):
                                    teacher_color = "#2563EB"
                                teacher_initials = str(lesson["teacher_initials"] or "").strip().upper()
                                if not teacher_initials:
                                    name_parts = [part for part in str(lesson["teacher_name"] or "").split() if part]
                                    teacher_initials = "".join(part[0] for part in (name_parts[:1] + (name_parts[-1:] if len(name_parts) > 1 else []))).upper()[:4] or "—"
                                subject_initial = str(lesson["subject_initial"] or "").strip().upper() or "—"
                                room_html = "" if view_type == "room" else f"<div class='tb-meta tb-room-label'>⌂ {esc(lesson['room_name'] or 'Room not assigned')}</div>"
                                class_label = esc(str(lesson["class_name"]) + ((" · " + str(lesson["stream"])) if lesson["stream"] else ""))
                                teacher_footer = (
                                    f"<div class='tb-lesson-footer'><span class='tb-meta tb-class-label'>{class_label}</span></div>"
                                    if view_type in ("teacher", "room")
                                    else f"<div class='tb-lesson-footer'><span class='tb-teacher-initials' title='{esc(lesson['teacher_name'])}'>{esc(teacher_initials)}</span></div>"
                                )
                                cards.append(
                                    f"<div class='tb-lesson {'tb-lesson-double' if duration > 1 else ''}' style='--teacher-color:{teacher_color}' title='{esc(lesson['subject_name'])} · {esc(lesson['teacher_name'])}'>"
                                    f"<div class='tb-lesson-top'><b class='tb-subject-initials'>{esc(subject_initial)}</b><span>{duration}P</span></div>"
                                    f"{room_html}{teacher_footer}</div>"
                                )
                            cells.append(f"<td class='tb-cell tb-cell-multi {'tb-cell-double' if cell_span > 1 else ''}' colspan='{cell_span}'>{''.join(cards)}</td>")
                        elif continued_lessons:
                            continued_cards = []
                            for item in continued_lessons:
                                continued_avatar = ""
                                if view_type not in ("teacher", "room"):
                                    continued_avatar = f" <b class='tb-teacher-initials'>{esc(str(item['teacher_initials'] or '').strip().upper() or '—')}</b>"
                                continued_cards.append(
                                    f"<div class='tb-continued-item' style='--teacher-color:{str(item['teacher_color'] or '#2563EB')}' title='{esc(item['subject_name'])} · {esc(item['teacher_name'])}'>↳ {esc(str(item['subject_initial'] or '').strip().upper() or '—')} continues{continued_avatar}</div>"
                                )
                            continued_html = "".join(continued_cards)
                            cells.append(f"<td class='tb-cell tb-continued'>{continued_html}</td>")
                        else:
                            cells.append("<td class='tb-cell tb-free'></td>")
                    row_class = " class='tb-day-end'" if class_index == len(day_class_rows) - 1 else ""
                    rows.append(f"<tr{row_class}>{''.join(cells)}</tr>")
            compact_view = str(selected['profile_type'] or 'main').strip().lower() != 'main'
            grid_class = 'tb-grid tb-grid-compact' if compact_view else 'tb-grid'
            grid = "<div class='tb-grid-scroll'><table class='" + grid_class + "'><thead><tr>" + "".join(headers) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        view_error_html = f"<div class='tv-alert'>{esc(view_error)}</div>" if view_error else ""
        export_query = f"profile_id={pid}&view_type={view_type}&class_id={int(class_id)}&teacher_id={int(teacher_id)}&room_id={int(room_id)}&remedial_display={remedial_display}"
        summary_html = (
            f"<div class='tv-summary'><div><b>{esc(result['title'])}</b><br><span>{esc(selected['academic_year'])} · {esc(selected['term'])}</span></div><span>{lesson_count} scheduled periods</span></div>"
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
        .tv-wrap{{max-width:1600px;margin:auto;padding:20px;color:#173d2b}}.tv-hero{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}}.tv-hero h2{{font-size:25px;margin:3px 0 5px}}.tv-hero p{{font-size:12px;color:#64748b;margin:0}}.tv-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}.tv-actions{{display:flex;gap:8px;flex-wrap:wrap}}.tv-btn{{display:inline-flex;padding:10px 14px;border:0;border-radius:9px;background:#17633b;color:white;text-decoration:none;font-size:12px;font-weight:800;cursor:pointer}}.tv-btn.secondary{{background:#edf6ef;color:#17633b;border:1px solid #d5e8d8}}.tv-filter{{display:grid;grid-template-columns:1.2fr 1fr 1fr 1fr auto;gap:10px;align-items:end;background:white;border:1px solid #e1ebe3;border-radius:14px;padding:15px;margin-bottom:15px}}.tv-filter label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:#334155}}.tv-filter select{{padding:10px;border:1px solid #dce7de;border-radius:9px;background:white;min-width:0;font-size:12px}}.tv-summary{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;background:white;border:1px solid #e1ebe3;border-radius:12px;padding:13px 15px;margin-bottom:14px}}.tv-extra-section{{margin-top:18px;background:#fff;border:1px solid #dce7de;border-radius:13px;padding:14px;break-inside:avoid}}.tv-extra-title{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}}.tv-extra-title h3{{margin:0;font-size:16px;color:#1d563b}}.tv-extra-title span{{font-size:10px;color:#647b6a}}.tv-session-scroll{{overflow:auto}}.tv-session-table{{width:100%;border-collapse:collapse;font-size:11px}}.tv-session-table th{{background:#17633b;color:white;text-align:left;padding:8px}}.tv-session-table td{{padding:7px;border-bottom:1px solid #e4ece5}}.tv-session-empty{{padding:10px;color:#64748b;font-size:11px}}.tv-weekend-sheet{{border:2px solid #b8d2bd}}.tv-remedial-separate{{background:#f8fbf8}}.tv-summary b{{font-size:16px}}.tv-summary span{{font-size:11px;color:#64748b}}.tv-dialog{{border:0;border-radius:16px;padding:0;width:min(560px,calc(100% - 24px));max-width:560px;box-shadow:0 22px 70px rgba(20,55,32,.28)}}.tv-dialog::backdrop{{background:rgba(17,38,24,.48);backdrop-filter:blur(3px)}}.tv-dialog .tv-filter{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;background:#fff;border:0;border-radius:16px;padding:18px;margin:0}}.tv-dialog-head{{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}}.tv-dialog-head b,.tv-dialog-head span{{display:block}}.tv-dialog-head b{{font-size:16px;color:#1d563b}}.tv-dialog-head span{{font-size:11px;color:#718276;margin-top:4px}}.tv-close{{border:0;background:#edf5ee;color:#285d3a;border-radius:9px;width:34px;height:34px;font-size:22px;cursor:pointer}}.tv-dialog-actions{{grid-column:1/-1;display:flex;justify-content:flex-end;gap:8px;margin-top:5px}}.tv-export-content{{display:grid;gap:10px;padding:18px}}.tv-export-content>.tv-btn{{justify-content:center}}.tv-view-actions{{margin:0 0 12px}}.tv-grid-scroll{{overflow:auto;border:1px solid #dce8de;border-radius:15px;background:white;box-shadow:0 6px 20px rgba(36,83,52,.045)}}.tv-grid{{width:100%;border-collapse:separate;border-spacing:0;min-width:995px}}.tv-grid thead th{{background:linear-gradient(110deg,#347b50,#286743);color:white;padding:8px 7px;text-align:center;font-size:12px;position:sticky;top:0;min-width:135px;border-bottom:5px solid #b7d1bc!important}}.tv-grid thead th.tb-period-heading{{border-right:2px solid #8eaf95!important}}.tv-grid .tb-day-heading{{min-width:115px;background:#edf5ee;color:#315b3e;text-align:center;vertical-align:middle;position:sticky;left:0;z-index:2}}.tv-grid .tb-class-heading{{width:76px;min-width:76px;max-width:76px;box-sizing:border-box;padding:6px 4px;background:#f5f9f5;color:#315b3e;text-align:center;vertical-align:middle;position:sticky;left:115px;z-index:1;font-size:9px;line-height:1.15;overflow-wrap:anywhere}}.tv-grid .tb-class-name,.tv-grid .tb-stream-name{{display:block}}.tv-grid .tb-class-name{{font-size:9px;font-weight:800}}.tv-grid .tb-stream-name{{margin-top:2px;color:#64816a;font-size:8px;font-weight:700}}.tv-grid .tb-period-heading b,.tv-grid .tb-period-heading span,.tv-grid .tb-break-heading b,.tv-grid .tb-break-heading span{{display:block}}.tv-grid tbody tr>th,.tv-grid tbody tr>td{{border-bottom:2px solid #c7d9ca!important}}.tv-grid tbody tr.tb-day-end>th,.tv-grid tbody tr.tb-day-end>td{{border-bottom:5px solid #6f9b78!important}}.tv-grid tbody .tb-day-heading{{vertical-align:middle;text-align:center;white-space:nowrap;box-shadow:inset 0 -3px 0 #6f9b78}}.tv-grid .tb-break-heading,.tv-grid .tb-break-cell{{background:#f1ead8!important;color:#75551d;text-align:center;min-width:115px;padding:10px 8px}}.tv-grid .tb-break-heading span{{color:#75551d}}.tv-grid .tb-break-cell b{{display:inline-block;writing-mode:vertical-rl;text-orientation:mixed;vertical-align:middle;line-height:1.1}}.tv-grid .tb-week-break{{vertical-align:middle!important;border-bottom:5px solid #6f9b78!important}}.tv-grid .tb-break-cell span{{display:block;font-size:10px;margin-top:4px}}.tv-grid .tb-cell{{height:82px;min-width:125px;vertical-align:middle;text-align:center;padding:4px;border-right:2px solid #b4cbb8;border-bottom:1px solid #edf2ed;background:#fff}}.tv-grid .tb-cell-multi{{height:82px;vertical-align:middle;text-align:center}}.tv-grid .tb-free{{background:#fbfdfb;text-align:center;vertical-align:middle;color:#a2b3a5;font-size:10px}}.tv-grid .tb-lesson{{--teacher-color:#287447;position:relative;box-sizing:border-box;background:color-mix(in srgb,var(--teacher-color) 17%,white);border:1px solid color-mix(in srgb,var(--teacher-color) 48%,white);border-left:4px solid var(--teacher-color);border-radius:8px;padding:5px 7px;min-height:66px;color:#234638;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;text-align:center;gap:2px;box-shadow:0 2px 7px rgba(35,83,51,.07)}}.tv-grid .tb-lesson-top{{display:flex;justify-content:center;align-items:center;gap:9px;font-size:10px;width:100%}}.tv-grid .tb-lesson-top span{{position:absolute;top:4px;right:5px;font-size:9px;background:#d5e9d9;border-radius:10px;padding:2px 5px}}.tv-grid .tb-subject-initials{{font-size:12px;letter-spacing:.5px;font-weight:900}}.tv-grid .tb-meta{{font-size:8px;color:#55705d;margin-top:2px}}.tv-grid .tb-room-label{{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.tv-grid .tb-lesson-footer{{display:flex;align-items:center;justify-content:flex-end;width:100%;min-height:14px;margin-top:auto}}.tv-grid .tb-teacher-initials{{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:16px;padding:0 4px;border-radius:5px;background:#245b39;color:#fff;font-size:8px;font-weight:950}}.tv-grid{{width:100%;border-collapse:separate;border-spacing:0;min-width:850px}}.tv-grid thead th{{background:#17633b;color:white;padding:13px 10px;text-align:center;font-size:12px;position:sticky;top:0;min-width:135px}}.tv-grid .tv-day-heading{{min-width:115px;background:#f0f6f1;color:#315b3e;text-align:left;position:sticky;left:0;z-index:2}}.tv-day-heading b,.tv-day-heading span,.tv-period-heading b,.tv-period-heading span,.tv-break-heading b,.tv-break-heading span{{display:block}}.tv-period-heading span,.tv-break-heading span{{font-size:10px;color:#e0eee3;font-weight:600;margin-top:4px}}.tv-break-heading,.tv-break-cell{{background:#f1ead8!important;color:#75551d;text-align:center;min-width:115px;padding:10px 8px;border-bottom:1px solid #e5d8b9}}.tv-break-heading span{{color:#75551d}}.tv-break-cell span{{display:block;font-size:10px;margin-top:4px}}.tv-break-row td{{border-bottom:1px solid #e5d8b9}}.tv-cell{{height:104px;min-width:145px;vertical-align:top;padding:6px;border-right:1px solid #edf2ed;border-bottom:1px solid #edf2ed}}.tv-lesson{{background:#eaf5ec;border-left:3px solid #287447;border-radius:8px;padding:7px;margin-bottom:5px;font-size:10px;color:#173d2b}}.tv-lesson b,.tv-lesson span,.tv-lesson small{{display:block}}.tv-lesson span{{font-weight:800;margin-top:4px}}.tv-lesson small{{font-size:9px;color:#55705d;margin-top:3px}}.tv-free{{text-align:center;vertical-align:middle;color:#c0ccc1;font-size:12px}}.tv-continued{{text-align:center;vertical-align:middle;background:#f6faf6;color:#7b9480;font-size:10px}}.tv-alert{{padding:11px 14px;background:#fff7e8;color:#8b5b14;border-radius:9px;margin-bottom:12px;font-size:12px}}.tv-empty{{padding:30px;text-align:center;color:#64748b;background:white;border:1px dashed #cdddcf;border-radius:12px}}@media(max-width:900px){{.tv-filter{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:600px){{.tv-wrap{{padding:12px}}.tv-dialog .tv-filter{{grid-template-columns:1fr}}.tv-hero h2{{font-size:22px}}}}@page{{size:A4 landscape;margin:8mm}}@media print{{.tv-hero .tv-actions,.tv-filter,.tv-alert{{display:none!important}}.tv-remedial-separate{{break-before:page}}.tv-weekend-sheet{{break-before:page}}.tv-session-scroll{{overflow:visible}}.tv-session-table{{font-size:9px}}.tv-wrap{{padding:0;max-width:none}}.tv-grid-scroll{{overflow:visible;border:1px solid #999}}.tv-grid{{min-width:0}}.tv-grid thead th{{position:static;background:#eaf5ec!important;color:#173d2b!important}}.tv-cell{{height:auto;min-width:0}}}}
        /* Keep the read-only grid visually identical to the Manual Timetable Builder. */
        .tv-wrap{{max-width:1700px;margin:auto;padding:12px;color:#234638;background:linear-gradient(145deg,#edf6ef 0%,#e3f0e5 45%,#f8fbf8 100%);border-radius:25px}}
        .tv-wrap *{{box-sizing:border-box}}
        .tv-wrap .tb-grid-scroll{{overflow:auto;border:1px solid #dce8de;border-radius:15px;background:#fff;box-shadow:0 6px 20px rgba(36,83,52,.045)}}
        .tv-wrap .tb-grid{{width:100%;border-collapse:separate;border-spacing:0;min-width:995px}}
        .tv-wrap .tb-grid thead th{{background:linear-gradient(110deg,#347b50,#286743);color:#fff;padding:8px 7px;text-align:center;font-size:12px;position:sticky;top:0;min-width:135px;border-bottom:5px solid #b7d1bc!important}}
        .tv-wrap .tb-grid thead th.tb-period-heading{{border-right:2px solid #8eaf95!important}}
        .tv-wrap .tb-grid .tb-day-heading{{min-width:115px;background:#edf5ee;color:#315b3e;text-align:center;vertical-align:middle;position:sticky;left:0;z-index:2;white-space:nowrap}}
        .tv-wrap .tb-grid .tb-class-heading{{width:76px;min-width:76px;max-width:76px;padding:6px 4px;background:#f5f9f5;color:#315b3e;text-align:center;vertical-align:middle;position:sticky;left:115px;z-index:1;font-size:9px;line-height:1.15;overflow-wrap:anywhere}}
        .tv-wrap .tb-grid .tb-class-name,.tv-wrap .tb-grid .tb-stream-name{{display:block}}
        .tv-wrap .tb-grid .tb-class-name{{font-size:9px;font-weight:800}}
        .tv-wrap .tb-grid .tb-stream-name{{margin-top:2px;color:#64816a;font-size:8px;font-weight:700}}
        .tv-wrap .tb-grid .tb-period-heading b,.tv-wrap .tb-grid .tb-period-heading span,.tv-wrap .tb-grid .tb-break-heading b,.tv-wrap .tb-grid .tb-break-heading span{{display:block}}
        .tv-wrap .tb-grid tbody tr>th,.tv-wrap .tb-grid tbody tr>td{{border-bottom:2px solid #c7d9ca!important}}
        .tv-wrap .tb-grid tbody tr.tb-day-end>th,.tv-wrap .tb-grid tbody tr.tb-day-end>td{{border-bottom:5px solid #6f9b78!important}}
        .tv-wrap .tb-grid tbody .tb-day-heading{{vertical-align:middle;text-align:center;box-shadow:inset 0 -3px 0 #6f9b78}}
        .tv-wrap .tb-grid .tb-break-heading,.tv-wrap .tb-grid .tb-break-cell{{background:#f1ead8!important;color:#75551d;text-align:center;min-width:115px;padding:10px 8px}}
        .tv-wrap .tb-grid .tb-break-heading span{{color:#75551d}}
        .tv-wrap .tb-grid .tb-break-cell span{{display:block;font-size:10px;margin-top:4px}}
        .tv-wrap .tb-grid .tb-cell{{height:82px;min-width:125px;vertical-align:middle;text-align:center;padding:4px;border-right:2px solid #b4cbb8;border-bottom:1px solid #edf2ed;background:#fff}}
        .tv-wrap .tb-grid .tb-cell-multi{{height:auto;min-height:82px;vertical-align:middle;text-align:center;display:table-cell}}
        .tv-wrap .tb-grid .tb-cell-multi .tb-lesson{{margin:0 auto 4px}}
        .tv-wrap .tb-grid .tb-cell-multi .tb-lesson:last-child{{margin-bottom:0}}
        .tv-wrap .tb-grid .tb-cell-double{{vertical-align:middle!important;padding:4px!important}}
        .tv-wrap .tb-grid .tb-cell-double .tb-lesson-double{{width:100%;height:66px;min-height:66px;max-height:66px;padding:7px;gap:0;overflow:hidden}}
        .tv-wrap .tb-grid .tb-free{{background:#fbfdfb;text-align:center;vertical-align:middle;color:#a2b3a5;font-size:10px}}
        .tv-wrap .tb-grid .tb-continued{{background:#f6faf6;color:#7b9480;text-align:center;vertical-align:middle;font-size:10px}}
        .tv-wrap .tb-grid .tb-continued-item{{padding:5px 7px;border-left:3px solid var(--teacher-color,#2563EB);background:color-mix(in srgb,var(--teacher-color,#2563EB) 13%,white);border-bottom:1px dashed #dce9de;font-size:9px;line-height:1.3;text-align:center}}
        .tv-wrap .tb-grid .tb-continued-item:last-child{{border-bottom:0}}
        .tv-wrap .tb-grid .tb-lesson{{--teacher-color:#2563EB;position:relative;box-sizing:border-box;background:color-mix(in srgb,var(--teacher-color) 17%,white);border:1px solid color-mix(in srgb,var(--teacher-color) 48%,white);border-left:4px solid var(--teacher-color);border-radius:8px;padding:5px 7px;min-height:66px;color:#234638;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;text-align:center;gap:2px;box-shadow:0 2px 7px rgba(35,83,51,.07)}}
        .tv-wrap .tb-grid .tb-lesson-top{{position:static;display:flex;justify-content:center;align-items:center;gap:9px;font-size:10px;width:100%}}
        .tv-wrap .tb-grid .tb-lesson-top span{{position:absolute;top:4px;right:5px;font-size:9px;background:#d5e9d9;border-radius:10px;padding:2px 5px}}
        .tv-wrap .tb-grid .tb-subject-initials{{font-size:12px;letter-spacing:.5px;font-weight:950}}
        .tv-wrap .tb-grid .tb-meta{{font-size:8px;color:#55705d;margin-top:2px}}
        .tv-wrap .tb-grid .tb-room-label{{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
        .tv-wrap .tb-grid .tb-class-label{{font-size:9px;font-weight:850;color:#315f43;line-height:1.15;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
        .tv-wrap .tb-grid .tb-lesson-footer{{display:flex;align-items:center;justify-content:flex-end;width:100%;min-height:14px;margin-top:auto}}
        .tv-wrap .tb-grid .tb-teacher-initials{{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:16px;padding:0 4px;box-sizing:border-box;border-radius:5px;background:color-mix(in srgb,var(--teacher-color) 78%,#173b29);color:#fff;text-shadow:0 1px 1px rgba(0,0,0,.22);font-size:8px;font-weight:950;letter-spacing:.04em;line-height:1}}
        .tv-wrap .tv-hero{{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:12px;padding:12px 16px;border:1px solid #d1e3d4;border-radius:18px;background:linear-gradient(118deg,#dceede,#c9e2ce 53%,#edf5eb)}}
        .tv-wrap .tv-hero h2{{font-size:clamp(19px,2vw,24px);margin:2px 0;color:#1e4934}}
        .tv-wrap .tv-hero p{{display:none}}
        .tv-wrap .tv-kicker{{font-size:10px;font-weight:900;letter-spacing:.12em;color:#43845a}}
        .tv-wrap .tv-actions{{display:flex;gap:8px;flex-wrap:wrap}}
        .tv-wrap .tv-btn{{display:inline-flex;align-items:center;justify-content:center;padding:11px 15px;border:0;border-radius:10px;background:linear-gradient(135deg,#347c50,#246441);color:#fff;text-decoration:none;font-size:12px;font-weight:800;cursor:pointer;min-height:40px}}
        .tv-wrap .tv-btn.secondary{{background:#edf6ee;color:#2a6a43;border:1px solid #cfe2d2}}
        @media(max-width:600px){{.tv-wrap{{padding:10px;border-radius:16px}}.tv-wrap .tv-grid-scroll{{border-radius:11px}}}}
        @media print{{.tv-wrap{{padding:0;max-width:none;background:#fff}}.tv-wrap .tv-grid-scroll{{overflow:visible;border:1px solid #999}}.tv-wrap .tb-grid{{min-width:0}}.tv-wrap .tb-grid thead th{{position:static;background:#347b50!important;color:#fff!important}}.tv-wrap .tb-grid .tb-cell{{min-width:0}}}}
        /* Match the teacher portal's non-main programme density; main stays unchanged. */
        .tv-wrap .tb-grid-compact{{min-width:500px;table-layout:fixed}}
        .tv-wrap .tb-grid-compact .tb-day-heading{{width:42px;min-width:42px;max-width:42px;padding:5px 2px;font-size:9px;overflow-wrap:anywhere}}
        .tv-wrap .tb-grid-compact .tb-class-heading{{left:42px}}
        .tv-wrap .tb-grid-compact thead th.tb-break-heading{{width:34px;min-width:34px;max-width:34px;padding:5px 1px;font-size:8px;overflow-wrap:anywhere;white-space:normal}}
        .tv-wrap .tb-grid-compact .tb-break-cell{{width:34px;min-width:34px;max-width:34px;padding:4px 2px}}
        .tv-wrap .tb-grid .tb-break-cell b{{writing-mode:vertical-rl;text-orientation:mixed;display:block;width:100%;height:100%;min-height:100%;text-align:justify;text-align-last:justify;vertical-align:middle;line-height:1;font-size:18px;font-weight:900;letter-spacing:.12em;white-space:nowrap}}
        .tv-wrap .tb-grid-compact thead th.tb-period-heading{{width:41px;min-width:41px;max-width:41px;padding:5px 2px;font-size:9px;overflow-wrap:anywhere}}
        .tv-wrap .tb-grid-compact tbody td.tb-cell{{width:41px;min-width:41px;max-width:41px;padding:2px;overflow:hidden}}
        .tv-wrap .tb-grid-compact .tb-lesson{{padding:3px 2px;min-height:48px;gap:1px;border-left-width:2px;border-radius:5px}}
        .tv-wrap .tb-grid-compact .tb-subject-initials{{font-size:9px;letter-spacing:0}}
        .tv-wrap .tb-grid-compact .tb-lesson-top{{font-size:8px;gap:1px}}
        .tv-wrap .tb-grid-compact .tb-lesson-top span{{position:absolute;top:2px;right:2px;font-size:7px;padding:1px 3px}}
        .tv-wrap .tb-grid-compact .tb-meta{{font-size:7px;line-height:1.05}}
        .tv-wrap .tb-grid-compact .tb-teacher-initials{{min-width:15px;height:13px;padding:0 2px;font-size:7px}}
        .tv-wrap .tb-grid-compact .tb-continued-item{{padding:2px;font-size:7px;line-height:1.1}}
        .tv-wrap .tb-grid-compact .tb-break-heading{{width:34px;min-width:34px;max-width:34px}}
        .tv-wrap .tb-grid-compact .tb-break-cell{{width:34px;min-width:34px;max-width:34px;padding:0;position:relative}}
        .tv-wrap .tb-grid .tb-break-cell{{position:relative;padding:0}}
        .tv-wrap .tb-grid .tb-break-cell b{{position:absolute;inset:3px 0;display:flex;flex-direction:column;justify-content:space-evenly;align-items:center;white-space:nowrap;overflow:hidden;line-height:1.0}}
        .tv-wrap .tb-grid .tb-break-cell b i{{display:block;font-style:normal;font-size:clamp(20px,3.4vh,34px);font-weight:950;line-height:1;letter-spacing:0}}
        .tv-wrap .tb-grid .tb-week-break{{vertical-align:middle!important}}
        .tv-wrap .tb-grid .tb-week-break{{vertical-align:middle!important}}
        /* Match the teacher portal: one centered character per line across the merged break column. */
        .tv-wrap .tb-grid .tb-break-cell>span{{position:absolute;inset:3px 0;display:flex;flex-direction:column;justify-content:space-evenly;align-items:center;writing-mode:horizontal-tb;text-orientation:mixed;white-space:nowrap;overflow:hidden;line-height:1;margin:0;padding:0;font-size:inherit;font-weight:950}}
        .tv-wrap .tb-grid .tb-break-cell>span i{{display:block;font-style:normal;font-size:clamp(20px,3.4vh,34px);font-weight:950;line-height:1;letter-spacing:0}}
        </style>
        <div class='tv-wrap'><div class='tv-hero'><div><span class='tv-kicker'>DAVISCHOOL · TIMETABLE VIEWS</span><h2>Timetable Views</h2><p>Inspect the published or draft timetable by school, class, teacher or room.</p></div></div>{notice}
        <div class='tv-actions tv-view-actions'><button type='button' class='tv-btn' onclick="document.getElementById('tv-filter-dialog').showModal()">Choose timetable view</button><button type='button' class='tv-btn secondary' onclick="document.getElementById('tv-export-dialog').showModal()">Export / print</button></div>
        <dialog id='tv-filter-dialog' class='tv-dialog'><form method='get' action='/app/timetable/views' class='tv-filter'><div class='tv-dialog-head'><div><b>Timetable view settings</b><span>Select the timetable and the group to display</span></div><button type='button' class='tv-close' onclick="this.closest('dialog').close()">×</button></div><label>Academic timetable<select name='profile_id'>{profile_options}</select></label><label>View type<select name='view_type'><option value='school' {'selected' if view_type=='school' else ''}>Whole school</option><option value='class' {'selected' if view_type=='class' else ''}>Class / stream</option><option value='teacher' {'selected' if view_type=='teacher' else ''}>Teacher</option><option value='room' {'selected' if view_type=='room' else ''}>Room / facility</option></select></label><label>Class / stream<select name='class_id' onchange="this.form.elements.view_type.value='class';this.form.elements.room_id.value='0';this.form.elements.teacher_id.value='0';">{class_options}</select></label><label>Teacher<select name='teacher_id' onchange="this.form.elements.view_type.value='teacher';this.form.elements.room_id.value='0';this.form.elements.class_id.value='0';">{teacher_options}</select></label><label>Room<select name='room_id' onchange="this.form.elements.view_type.value='room';this.form.elements.class_id.value='0';this.form.elements.teacher_id.value='0';">{room_options}</select></label><label>Weekday remedials<select name='remedial_display'><option value='combined' {'selected' if remedial_display=='combined' else ''}>Same sheet as normal lessons</option><option value='separate' {'selected' if remedial_display=='separate' else ''}>Separate remedial sheet</option></select></label><div class='tv-dialog-actions'><button type='button' class='tv-btn secondary' onclick="this.closest('dialog').close()">Cancel</button><button class='tv-btn'>Apply view</button></div></form></dialog>
        <dialog id='tv-export-dialog' class='tv-dialog'><div class='tv-export-content'><div class='tv-dialog-head'><div><b>Export timetable</b><span>Choose how to use the displayed timetable</span></div><button type='button' class='tv-close' onclick="this.closest('dialog').close()">×</button></div><a class='tv-btn secondary' href='/app/timetable/export/pdf?{export_query}'>Export PDF</a><a class='tv-btn secondary' href='/app/timetable/export/xlsx?{export_query}'>Export Excel</a><a class='tv-btn' href='/app/timetable/export/print?{export_query}' target='_blank' rel='noopener'>Print timetable</a></div></dialog>
        {view_error_html}
        {summary_html}
        {grid}
        {dated_instructional_html}
        {weekday_remedial_html}
        {weekend_html}
        </div>
        """
        return module_page(request, "Timetable Views", "timetable", body)
