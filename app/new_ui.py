    con=_db(); cur=con.cursor()
    try:
        teacher=cur.execute("SELECT id,name,email,role FROM teachers WHERE id=? AND school_id=?",(teacher_id,sid)).fetchone()
        if not teacher:
            return JSONResponse({"classes":[],"subjects_by_class":{},"teacher_type":"subject_teacher"})
        _ensure_teacher_allocations_table(cur)
        _ensure_class_teacher_assignments_table(cur)
        allocations=cur.execute("""SELECT a.class_id,a.subject_id,c.name class_name,c.stream,s.name subject_name
            FROM teacher_allocations a
            JOIN classes c ON c.id=a.class_id AND c.school_id=a.school_id
            JOIN subjects s ON s.id=a.subject_id AND s.school_id=a.school_id
            WHERE a.school_id=? AND a.teacher_id=?
            ORDER BY c.name,c.stream,s.name""",(sid,teacher_id)).fetchall()
        class_teacher=cur.execute("SELECT class_id FROM class_teacher_assignments WHERE school_id=? AND teacher_id=? LIMIT 1",(sid,teacher_id)).fetchone()
        classes=[]
        subjects_by_class={}
        for row in allocations:
            cid=int(row["class_id"])
            if cid not in classes:
                classes.append(cid)
            subjects_by_class.setdefault(str(cid),[])
            if int(row["subject_id"]) not in subjects_by_class[str(cid)]:
                subjects_by_class[str(cid)].append(int(row["subject_id"]))
        if class_teacher and int(class_teacher["class_id"]) not in classes:
            classes.append(int(class_teacher["class_id"]))
        ct=bool(class_teacher)
        st=bool(allocations)
        teacher_type="both" if ct and st else ("class_teacher" if ct else "subject_teacher")
        return JSONResponse({"teacher":{"id":int(teacher["id"]),"name":str(teacher["name"] or ""),"email":str(teacher["email"] or "")},
            "classes":classes,"subjects_by_class":subjects_by_class,
            "class_teacher_class":int(class_teacher["class_id"]) if class_teacher else None,
            "teacher_type":teacher_type})
    finally:
        con.close()


@router.get("/app/users/add")
def users_add_get(request: Request):
    # The account-creation endpoint is POST-only. Redirect accidental GET
    # requests back to User Management instead of exposing FastAPI's 405 JSON.
    return RedirectResponse("/app/users",303)

@router.post("/app/users")
def users_add_legacy(request: Request, email:str=Form(""), role:str=Form("teacher"), teacher_id:str=Form(""), class_id:str=Form(""), class_ids_csv:str=Form(""), subject_ids_csv:str=Form(""), teacher_type:str=Form("subject_teacher"), student_id:str=Form("")):
    # Compatibility for browsers or cached scripts that submit the User Management
    # account form to /app/users instead of its dedicated /app/users/add action.
    # Keep this path strictly delegated so there is only one account-creation flow.
    return users_add(request, email, role, teacher_id, class_id, class_ids_csv, subject_ids_csv, teacher_type, student_id)

@router.post("/app/users/add")
def users_add(request: Request, email:str=Form(""), role:str=Form("teacher"), teacher_id:str=Form(""), class_id:str=Form(""), class_ids_csv:str=Form(""), subject_ids_csv:str=Form(""), teacher_type:str=Form("subject_teacher"), student_id:str=Form("")):
    sid=_school_session(request)
    if not sid:return RedirectResponse("/",303)
    if not _require_permission(request, sid, "users.manage"):
        return HTMLResponse("You do not have permission to manage users.", 403)
    email=(email or "").strip()
    allowed={"school_admin","teacher","parent","student","accountant","registrar"}
    if role not in allowed:return HTMLResponse("Invalid role. <a href='/app/users'>Back</a>",400)
    # School Admin accounts are created only by the Super Admin, not from the school-level User Management page.
    if role=="school_admin":
        return HTMLResponse("School Admin accounts can only be created by the Super Admin.",403)
    con=_db();cur=con.cursor()
    try:
        _ensure_user_account_columns(cur, con)
        email_v=email.strip().lower()
        full_name=""
        tid=int(teacher_id) if teacher_id.isdigit() else None
        stid=int(student_id) if student_id.isdigit() else None

        if tid and not cur.execute("SELECT id,name,email FROM teachers WHERE id=? AND school_id=?",(tid,sid)).fetchone():
            return HTMLResponse("Selected teacher does not belong to this school. <a href='/app/users'>Back</a>",400)
        if stid and not cur.execute("SELECT id FROM students WHERE id=? AND school_id=?",(stid,sid)).fetchone():
            return HTMLResponse("Selected student does not belong to a student record in this school. <a href='/app/users'>Back</a>",400)
        if role=="teacher" and not tid:
            return HTMLResponse("Teacher accounts must be linked to a teacher profile selected from Teachers Records.",400)
        if role in ("student","parent") and not stid:
            return HTMLResponse("Student and parent accounts must be linked to a student profile. <a href='/app/users'>Back</a>",400)
        if role not in ("teacher","student","parent") and (tid or stid):
            return HTMLResponse("This role cannot be linked to a teacher or student profile. <a href='/app/users'>Back</a>",400)

        if role=="teacher":
            teacher_row=cur.execute("SELECT name,email FROM teachers WHERE id=? AND school_id=?",(tid,sid)).fetchone()
            if teacher_row:
                # The selected Teachers record is authoritative. This also
                # makes account creation work if browser-side JavaScript did
                # not populate the readonly name/email fields.
                full_name=str(teacher_row["name"] or "").strip()
                if teacher_row["email"] and not email_v:
                    email_v=str(teacher_row["email"]).strip().lower()

        # Teacher login credentials are based on the teacher record:
        # username = teacher email; password = first name + generated digits.
        # This keeps teacher credentials predictable for the school admin while
        # still making the initial password unique.
        if role=="teacher":
            if not email_v:
                return HTMLResponse("The selected teacher must have an email address before a teacher account can be created. Please add the email in Teachers Records and try again. <a href='/app/users'>Back</a>",400)
            existing_email_account=cur.execute(
                "SELECT id FROM users WHERE lower(username)=? OR (school_id=? AND lower(email)=?) LIMIT 1",
                (email_v,sid,email_v)
            ).fetchone()
            if existing_email_account:
                return HTMLResponse("A user account already exists for this teacher email. Please edit the existing account instead of creating another one. <a href='/app/users'>Back</a>",400)

        class_ids=[int(x) for x in str(class_ids_csv or "").split(",") if x.strip().isdigit()]
        subject_ids=[int(x) for x in str(subject_ids_csv or "").split(",") if x.strip().isdigit()]
        class_ids=list(dict.fromkeys(class_ids)); subject_ids=list(dict.fromkeys(subject_ids))

        if role=="teacher":
            if teacher_type not in ("class_teacher","subject_teacher","both"):
                teacher_type="subject_teacher"

            # The database is authoritative. If the browser did not submit the
            # hidden allocation fields, rebuild them from the teacher's existing
            # allocations/class-teacher assignment instead of rejecting the account.
            _ensure_teacher_allocations_table(cur)
            _ensure_class_teacher_assignments_table(cur)
            existing_allocations=cur.execute(
                "SELECT class_id,subject_id FROM teacher_allocations WHERE school_id=? AND teacher_id=? ORDER BY class_id,subject_id",
                (sid,tid)
            ).fetchall()
            existing_class_teacher=cur.execute(
                "SELECT class_id FROM class_teacher_assignments WHERE school_id=? AND teacher_id=? ORDER BY id DESC LIMIT 1",
                (sid,tid)
            ).fetchone()

            if not class_ids:
                class_ids=list(dict.fromkeys(int(x["class_id"]) for x in existing_allocations))
            if existing_class_teacher and int(existing_class_teacher["class_id"]) not in class_ids:
                class_ids.append(int(existing_class_teacher["class_id"]))
            if not subject_ids:
                subject_ids=list(dict.fromkeys(int(x["subject_id"]) for x in existing_allocations))

            # If exactly one class is selected and no subject is selected while
            # the default Subject Teacher option is unchanged, treat it as a
            # Class Teacher assignment only when that teacher is already assigned
            # as a class teacher. Otherwise retain Subject Teacher validation.
            if teacher_type=="subject_teacher" and len(class_ids)==1 and not subject_ids and existing_class_teacher:
                teacher_type="class_teacher"

            # Account creation must remain possible even when the allocation
            # selector submits no values. Existing teacher allocations are used
            # automatically; missing allocations should not block login creation.
            if teacher_type in ("class_teacher","both") and len(class_ids)!=1:
                if teacher_type=="both" and class_ids:
                    class_ids=[class_ids[0]]
                elif teacher_type=="class_teacher" and class_ids:
                    class_ids=[class_ids[0]]
                else:
                    teacher_type="subject_teacher"
            if teacher_type in ("subject_teacher","both") and (not class_ids or not subject_ids):
                # Keep the account creation independent of allocation selection.
                # Allocations can be edited from Teacher Links afterward.
                if not class_ids and existing_class_teacher:
                    class_ids=[int(existing_class_teacher["class_id"])]
                if not class_ids and existing_allocations:
                    class_ids=[int(existing_allocations[0]["class_id"])]
                if not subject_ids and existing_allocations:
                    subject_ids=list(dict.fromkeys(int(x["subject_id"]) for x in existing_allocations))
                if not class_ids or not subject_ids:
                    teacher_type="class_teacher" if existing_class_teacher and class_ids else "subject_teacher"

            if class_ids:
                valid_classes=cur.execute("SELECT id FROM classes WHERE school_id=? AND id IN (%s)"%(",".join("?"*len(class_ids)),),[sid]+class_ids).fetchall()
            else:
                valid_classes=[]
            if subject_ids:
                valid_subjects=cur.execute("SELECT id FROM subjects WHERE school_id=? AND id IN (%s)"%(",".join("?"*len(subject_ids)),),[sid]+subject_ids).fetchall()
            else:
                valid_subjects=[]
            if len(valid_classes)!=len(class_ids) or len(valid_subjects)!=len(subject_ids):
                return HTMLResponse("One or more selected classes/subjects do not belong to this school.",400)

        from app.main import hash_password, verify_password
        import secrets
        if role=="teacher":
            first_name=re.sub(r"[^A-Za-z0-9]", "", full_name.split()[0] if full_name.split() else "Teacher")
            generated_password=first_name+"@"+str(datetime.now(ZoneInfo("Africa/Nairobi")).year)
            username=email_v
        else:
            generated_password="DS-"+secrets.token_urlsafe(8)
            base_username=re.sub(r"[^a-z0-9]+","",full_name.lower()) or "user"
            username=base_username
            if username=="user" and tid:
                username="teacher"
            username=username[:40]
            username_suffix=secrets.randbelow(9000)+1000
            if cur.execute("SELECT id FROM users WHERE lower(username)=?",(username.lower(),)).fetchone():
                username=f"{username}{username_suffix}"
            suffix=1
            while cur.execute("SELECT id FROM users WHERE lower(username)=?",(username.lower(),)).fetchone():
                suffix += 1
                username=f"{base_username}{suffix}"
        # Build and verify the credential hash before inserting the account.
        # This guarantees that the credential displayed to the School Admin is
        # exactly the credential the login verifier can validate.
        password_hash=hash_password(generated_password)
        password_ok,_=verify_password(generated_password,password_hash)
        if not password_ok:
            return HTMLResponse("The generated password could not be validated. No account was added. Please try again.",500)
        cur.execute("INSERT INTO users(username,email,password,role,full_name,school_id,teacher_id,student_id,temporary_password) VALUES(?,?,?,?,?,?,?,?,?)",
                    (username,email_v,password_hash,role,full_name.strip(),sid,tid,stid,generated_password))

        if role=="teacher" and tid:
            _ensure_teacher_allocations_table(cur)
            _ensure_class_teacher_assignments_table(cur)
            if teacher_type in ("class_teacher","both"):
                cid=class_ids[0]
                now=datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y-%m-%d %H:%M:%S")
                # Do not rely on PostgreSQL ON CONFLICT here. Older DaviSchool
                # deployments can have these tables without the matching UNIQUE
                # constraint, which causes InvalidColumnReference and aborts the
                # whole account-creation transaction. Explicit lookup/update/insert
                # works safely with both the legacy schema and current schema.
                existing_class_teacher=cur.execute(
                    "SELECT id FROM class_teacher_assignments WHERE school_id=? AND class_id=? ORDER BY id DESC LIMIT 1",
                    (sid,cid)
                ).fetchone()
                if existing_class_teacher:
                    cur.execute(
                        "UPDATE class_teacher_assignments SET teacher_id=?,assigned_at=? WHERE id=? AND school_id=?",
                        (tid,now,existing_class_teacher["id"],sid)
                    )
                else:
                    cur.execute(
                        "INSERT INTO class_teacher_assignments(school_id,class_id,teacher_id,assigned_at) VALUES(?,?,?,?)",
                        (sid,cid,tid,now)
                    )
            if teacher_type in ("subject_teacher","both"):
                for cid in class_ids:
                    for subject_id in subject_ids:
                        existing_allocation=cur.execute(
                            "SELECT id FROM teacher_allocations WHERE school_id=? AND teacher_id=? AND class_id=? AND subject_id=? ORDER BY id DESC LIMIT 1",
                            (sid,tid,cid,subject_id)
                        ).fetchone()
                        if not existing_allocation:
                            cur.execute(
                                "INSERT INTO teacher_allocations(school_id,teacher_id,class_id,subject_id) VALUES(?,?,?,?)",
                                (sid,tid,cid,subject_id)
                            )

        try:
            _audit(cur,sid,request,"USER_CREATE",f"Created {role} account {email_v}")