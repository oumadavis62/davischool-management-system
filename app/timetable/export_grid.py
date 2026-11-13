"""Shared grid model for timetable screen-equivalent exports."""
from __future__ import annotations


def build_export_grid(result, view_type):
    days, periods = result["days"], result["periods"]
    timeline = sorted(
        [(str(p["start_time"]), "period", p) for p in periods] +
        [(str(b["start_time"]), "break", b) for b in result.get("breaks", [])],
        key=lambda item: (item[0], 0 if item[1] == "period" else 1),
    )
    period_index = {int(p["id"]): i for i, p in enumerate(periods)}
    timeline_pos = {int(item["id"]): pos for pos, (_, kind, item) in enumerate(timeline) if kind == "period"}
    lessons = result["lessons"]
    classes = {}
    if view_type == "school":
        for row in result.get("allocation_classes", []):
            classes[int(row["class_id"])] = {"class_id": int(row["class_id"]), "class_name": str(row["class_name"]), "stream": str(row["stream"] or ""), "class_initials": str(row["class_initials"] or "").strip().upper()}
    for lesson in lessons:
        classes.setdefault(int(lesson["class_id"]), {"class_id": int(lesson["class_id"]), "class_name": str(lesson["class_name"]), "stream": str(lesson["stream"] or ""), "class_initials": str(lesson.get("class_initials") or "").strip().upper()})
    if view_type == "class" and result.get("target"):
        target = result["target"]
        classes = {int(target["id"]): {"class_id": int(target["id"]), "class_name": str(target["name"]), "stream": str(target["stream"] or ""), "class_initials": ""}}
    rowspec = sorted(classes.values(), key=lambda x: (x["class_name"].casefold(), x["stream"].casefold()))
    if view_type in ("teacher", "room"):
        rowspec = [{"class_id": 0, "class_name": "", "stream": "", "class_initials": ""}]
    if not rowspec:
        rowspec = [{"class_id": 0, "class_name": "—", "stream": "", "class_initials": "—"}]
    starts, occupied = {}, {}
    for lesson in lessons:
        key = (int(lesson["day_id"]), int(lesson["class_id"]), int(lesson["period_id"]))
        starts.setdefault(key, []).append(lesson)
        start = period_index.get(int(lesson["period_id"]))
        if start is not None:
            for off in range(1, max(1, int(lesson["duration_periods"] or 1))):
                if start + off < len(periods):
                    occupied.setdefault((int(lesson["day_id"]), int(lesson["class_id"]), int(periods[start+off]["id"])), []).append(lesson)
    output_rows = []
    for day_index, day in enumerate(days):
        for class_index, class_row in enumerate(rowspec):
            cells, covered = [], set()
            for pos, (_, kind, item) in enumerate(timeline):
                if kind == "break":
                    if view_type in ("class", "teacher", "room"):
                        if day_index == 0 and class_index == 0:
                            cells.append({"kind":"break","item":item,"rowspan":len(days)})
                        else:
                            cells.append({"kind":"break_placeholder"})
                    elif day_index == 0 and class_index == 0:
                        # Match the timetable view: one vertical break label spans
                        # every day and class row in the exported grid.
                        cells.append({"kind":"break","item":item,"rowspan":len(days) * len(rowspec)})
                    else:
                        cells.append({"kind":"break_placeholder"})
                    continue
                pid = int(item["id"])
                if pid in covered:
                    continue
                if view_type in ("teacher", "room"):
                    slot = [x for x in lessons if int(x["day_id"]) == int(day["id"]) and int(x["period_id"]) == pid]
                    continued = [x for x in lessons if int(x["day_id"]) == int(day["id"]) and (int(day["id"]),int(x["class_id"]),pid) in occupied and x in occupied[(int(day["id"]),int(x["class_id"]),pid)]]
                else:
                    key=(int(day["id"]),int(class_row["class_id"]),pid)
                    slot, continued = starts.get(key, []), occupied.get(key, [])
                if slot:
                    span = 1
                    # A merged cell must represent one uninterrupted lesson.
                    # Previously, the longest duration in a shared slot could
                    # span over a different lesson starting in the next period,
                    # making that scheduled lesson disappear from the export.
                    # Only merge a single-lesson slot, and only when no other
                    # lesson for this view starts in any period being covered.
                    if len(slot) == 1:
                        lesson = slot[0]
                        duration = max(1, int(lesson["duration_periods"] or 1))
                        start = period_index.get(int(lesson["period_id"]))
                        span_periods = [
                            periods[start + off]
                            for off in range(duration)
                            if start is not None and start + off < len(periods)
                        ]
                        can_merge = (
                            len(span_periods) == duration
                            and all(
                                timeline_pos.get(int(span_periods[off]["id"])) == pos + off
                                for off in range(duration)
                            )
                        )
                        covered_period_ids = {
                            int(periods[start + off]["id"])
                            for off in range(1, duration)
                        } if start is not None and len(span_periods) == duration else set()
                        has_new_lesson = any(
                            int(other["day_id"]) == int(day["id"])
                            and int(other["period_id"]) in covered_period_ids
                            and (
                                view_type in ("teacher", "room")
                                or int(other["class_id"]) == int(class_row["class_id"])
                            )
                            for other in lessons
                        )
                        if can_merge and not has_new_lesson:
                            span = duration
                    if span > 1:
                        for off in range(1, span):
                            covered.add(int(periods[period_index[pid] + off]["id"]))
                    cells.append({"kind":"lesson","lessons":slot,"span":span})
                elif continued:
                    cells.append({"kind":"continued","lessons":continued,"span":1})
                else:
                    cells.append({"kind":"free","span":1})
            output_rows.append({"day":day,"class":class_row,"day_first":class_index==0,"day_rowspan":len(rowspec),"cells":cells})
    return {"timeline":timeline,"rows":output_rows,"show_class_column":view_type=="school","resource_view":view_type in ("teacher","room"),"room_view":view_type=="room","view_type":view_type}
