from fastapi import Request
from fastapi.responses import RedirectResponse
from urllib.parse import quote

def install_legacy_school_redirect(app):
    """Disable the legacy /school interface and handle school verification safely."""
    @app.middleware("http")
    async def redirect_legacy_school(request: Request, call_next):
        path = request.url.path

        # The old school UI is disabled. Keep all school traffic on /app.
        if path == "/school" or path.startswith("/school/"):
            return RedirectResponse("/app", status_code=303)

        # Handle school verification before the old route can execute.
        # This prevents the legacy handler from producing a generic 500.
        if path == "/verify-school-code" and request.method.upper() == "POST":
            if request.session.get("role") != "super_admin":
                return RedirectResponse("/", status_code=303)

            try:
                form = await request.form()
                pending_id = str(form.get("pending_id") or "").strip()
                entered = "".join(ch for ch in str(form.get("auth_code") or "") if ch.isdigit())

                if not pending_id or not entered:
                    return RedirectResponse("/schools/manage?success=invalid_code", status_code=303)

                # Import lazily to avoid a circular import during startup.
                import app.main as core

                con = core.get_db()
                try:
                    cur = con.cursor()
                    pending = cur.execute(
                        "SELECT * FROM pending_schools WHERE id=?",
                        (pending_id,)
                    ).fetchone()

                    expected = str(pending["auth_code"]).strip() if pending else ""
                    if not pending or not core.hmac.compare_digest(entered, expected):
                        return RedirectResponse(
                            f"/schools/manage?success=invalid_code&pending_id={quote(pending_id)}",
                            status_code=303
                        )

                    # Prevent duplicate school-admin accounts.
                    existing = cur.execute(
                        "SELECT id FROM users WHERE lower(email)=lower(?) AND role='school_admin'",
                        (str(pending["email"]).strip(),)
                    ).fetchone()
                    if existing:
                        cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,))
                        con.commit()
                        return RedirectResponse(
                            "/schools/manage?success=already_added"
                            f"&school_email={quote(str(pending['email']))}"
                            f"&school_name={quote(str(pending['name']))}",
                            status_code=303
                        )

                    school_code = str(core.random.randint(100000, 999999))
                    unique_pass = core.generate_unique_password(str(pending["name"]))

                    cur.execute(
                        "INSERT INTO schools "
                        "(name,email,code,location,phone,principal,school_type) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (
                            pending["name"],
                            pending["email"],
                            school_code,
                            pending["location"],
                            pending["phone"],
                            pending["principal"],
                            pending["school_type"],
                        )
                    )
                    school_id = cur.lastrowid

                    cur.execute(
                        "INSERT INTO users "
                        "(email,password,role,full_name,school_id) "
                        "VALUES (?,?,?,?,?)",
                        (
                            str(pending["email"]).strip(),
                            core.hash_password(unique_pass),
                            "school_admin",
                            pending["principal"],
                            school_id,
                        )
                    )

                    cur.execute("DELETE FROM pending_schools WHERE id=?", (pending_id,))
                    con.commit()

                    return RedirectResponse(
                        "/schools/manage?success=added"
                        f"&new_pass={quote(unique_pass)}"
                        f"&school_email={quote(str(pending['email']))}"
                        f"&school_name={quote(str(pending['name']))}",
                        status_code=303
                    )

                except Exception as exc:
                    con.rollback()
                    # Log the exact server-side exception, but return the user
                    # to the visible verification panel instead of a 500.
                    print("DAVISCHOOL SCHOOL VERIFICATION ERROR:", repr(exc), flush=True)
                    return RedirectResponse(
                        f"/schools/manage?success=code_sent&pending_id={quote(pending_id)}",
                        status_code=303
                    )
                finally:
                    con.close()

            except Exception as exc:
                print("DAVISCHOOL SCHOOL VERIFICATION REQUEST ERROR:", repr(exc), flush=True)
                return RedirectResponse("/schools/manage?success=invalid_code", status_code=303)

        return await call_next(request)
