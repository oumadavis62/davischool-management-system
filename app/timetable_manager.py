                if fixed:
                    if any((day,xp,fixed) in room_slot for xp in range(int(pno),int(pno)+duration)):
                        return None
                    return fixed

                if rooms:
                    for room in rooms:
                        rid=int(room["id"])
                        if all((day,xp,rid) not in room_slot for xp in range(int(pno),int(pno)+duration)):
                            return rid

                # Room is optional. Zero means "no room assigned".
                return 0

            pending=list(occurrences)
            rng.shuffle(pending)
            pending.sort(key=lambda x:(
                -max(1,int(lesson_by_id[x[0]].get("duration") or 1)),
                -int(lesson_by_id[x[0]].get("lessons_per_week") or 0),
                len(all_candidates.get(x[0],[])),
                x[0],x[1]
            ))

            # Greedy placement with bounded look-ahead. We do not repeatedly
            # rescan the pending list; this keeps generation fast and stable.
            for lid,occ_no in pending:
                lesson=lesson_by_id[lid]
                choices=[]
                for day,pno in all_candidates.get(lid,[]):
                    room=placeable(lesson,day,pno)
                    if room is None:
                        continue
                    classes=lesson_classes[lid]
                    teachers=lesson_teachers[lid]
                    load=sum(class_day_load.get((day,c),0) for c in classes)
                    load+=sum(teacher_day_load.get((day,t),0) for t in teachers)

                    # aSc-style manual-balancing workflow: when different
                    # subjects for the same class can legally sit next to one
                    # another, prefer consecutive placement. The user can then
                    # drag the placards apart manually on the master sheet.
                    adjacent_class=0
                    for existing in occupied:
                        if str(existing["day_name"])!=day:
                            continue
                        existing_classes=lesson_classes.get(int(existing["lesson_id"]),{int(existing["class_id"])})
                        if not classes.intersection(existing_classes):
                            continue
                        existing_subject=int(existing.get("subject_id") or lesson_by_id[int(existing["lesson_id"])]["subject_id"])
                        if existing_subject==int(lesson["subject_id"]):
                            continue
                        ep=int(existing["period_no"])
                        ed=max(1,int(existing.get("duration") or 1))
                        if ep+ed==int(pno) or int(pno)+max(1,int(lesson.get("duration") or 1))==ep:
                            adjacent_class+=1

                    # Strong preference, not a hard rule: place different
                    # subjects for the same class consecutively when possible.
                    adjacency_bonus=-25*adjacent_class
                    choices.append((load+adjacency_bonus+int(pno)*0.01+rng.random(),day,int(pno),room))

                if not choices:
                    continue
                choices.sort(key=lambda x:x[0])

                committed=False
                for _,day,pno,room in choices[:12]:
                    checked=placeable(lesson,day,pno)
                    if checked is None:
                        continue
                    row={
                        "lesson_id":lid,
                        "class_id":lesson["class_id"],
                        "teacher_id":lesson["teacher_id"],