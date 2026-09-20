from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from urllib.parse import quote

def install_legacy_school_redirect(app):
    """Disable the legacy /school interface and handle school verification safely."""
    @app.middleware("http")
    async def redirect_legacy_school(request: Request, call_next):
        path = request.url.path

        if path == "/school" or path.startswith("/school/"):
            return RedirectResponse("/app", status_code=303)

        if path == "/verify-school-code" and request.method.upper() == "POST":
            if request.session.get("role") != "super_admin":
                return RedirectResponse("/", status_code=303)
            try:
                form = await request.form()
                pending_id = str(form.get("pending_id") or "").strip()
                entered = "".join(ch for ch in str(form.get("auth_code") or "") if ch.isdigit())
                if not pending_id or not entered:
                    return RedirectResponse("/schools/manage?success=invalid_code", status_code=303)

                import app.main as core
                con = core.get_db()
                try:
                    cur = con.cursor()
                    pending = cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,)).fetchone()
                    expected = str(pending["auth_code"]).strip() if pending else ""
                    if not pending or not core.hmac.compare_digest(entered, expected):
                        return RedirectResponse(
                            f"/schools/manage?success=invalid_code&pending_id={quote(pending_id)}",
                            status_code=303
                        )

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
                        "INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)",
                        (pending["name"], pending["email"], school_code, pending["location"],
                         pending["phone"], pending["principal"], pending["school_type"])
                    )
                    school_id = cur.lastrowid
                    cur.execute(
                        "INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)",
                        (str(pending["email"]).strip(), core.hash_password(unique_pass),
                         "school_admin", pending["principal"], school_id)
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
                    try:
                        con.rollback()
                    except Exception:
                        pass
                    error_text = str(exc)
                    print("DAVISCHOOL SCHOOL VERIFICATION ERROR:", repr(exc), flush=True)

                    # SQLite can briefly be locked when Render has multiple
                    # workers. Retry the complete write transaction a few times.
                    if "locked" in error_text.lower() or "busy" in error_text.lower():
                        import time
                        for attempt in range(3):
                            try:
                                time.sleep(0.35 * (attempt + 1))
                                con.close()
                                con = core.get_db()
                                cur = con.cursor()
                                pending = cur.execute(
                                    "SELECT * FROM pending_schools WHERE id=?",
                                    (pending_id,)
                                ).fetchone()
                                if not pending:
                                    break

                                existing = cur.execute(
                                    "SELECT id FROM users WHERE lower(email)=lower(?) AND role='school_admin'",
                                    (str(pending["email"]).strip(),)
                                ).fetchone()
                                if existing:
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
                                    "INSERT INTO schools (name,email,code,location,phone,principal,school_type) VALUES (?,?,?,?,?,?,?)",
                                    (pending["name"], pending["email"], school_code,
                                     pending["location"], pending["phone"], pending["principal"],
                                     pending["school_type"])
                                )
                                school_id = cur.lastrowid
                                cur.execute(
                                    "INSERT INTO users (email,password,role,full_name,school_id) VALUES (?,?,?,?,?)",
                                    (str(pending["email"]).strip(), core.hash_password(unique_pass),
                                     "school_admin", pending["principal"], school_id)
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
                            except Exception as retry_exc:
                                try:
                                    con.rollback()
                                except Exception:
                                    pass
                                print("DAVISCHOOL SCHOOL VERIFICATION RETRY ERROR:", repr(retry_exc), flush=True)

                    return RedirectResponse(
                        f"/schools/manage?success=verify_error"
                        f"&pending_id={quote(pending_id)}"
                        f"&message={quote(error_text[:180])}",
                        status_code=303
                    )
                finally:
                    con.close()
            except Exception as exc:
                print("DAVISCHOOL SCHOOL VERIFICATION REQUEST ERROR:", repr(exc), flush=True)
                return RedirectResponse("/schools/manage?success=invalid_code", status_code=303)

        response = await call_next(request)

        # Show the requested credential-success prompt after verification.
        if (
            path == "/schools/manage"
            and request.method.upper() == "GET"
            and request.query_params.get("success") == "added"
            and request.query_params.get("school_email")
            and request.query_params.get("school_name")
            and request.query_params.get("new_pass")
            and response.status_code == 200
        ):
            try:
                import html as _html
                school_name = _html.escape(str(request.query_params.get("school_name") or ""))
                email = _html.escape(str(request.query_params.get("school_email") or ""))
                password = _html.escape(str(request.query_params.get("new_pass") or ""))
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                page = body.decode("utf-8")
                success_prompt = f"""
<style>
.davi-success-overlay{{position:fixed;inset:0;background:rgba(15,23,42,.28);display:flex;align-items:center;justify-content:center;padding:20px;z-index:99999}}
.davi-success-card{{width:min(760px,96vw);background:#dcfce7;border:3px solid #16a34a;border-radius:18px;padding:28px;box-shadow:0 24px 70px rgba(15,23,42,.25);font-family:Arial,sans-serif}}
.davi-success-title{{font-size:25px;font-weight:900;color:#166534;margin-bottom:18px}}
.davi-credentials{{background:#fff;border:1.5px dashed #22c55e;border-radius:14px;padding:18px;margin-bottom:18px}}
.davi-label{{font-size:15px;color:#64748b;margin-top:8px}}
.davi-value{{font-size:25px;font-weight:900;color:#166534;word-break:break-word;margin-top:3px}}
.davi-ok{{display:block;margin-left:auto;background:#0f172a;color:white;border:0;border-radius:12px;padding:13px 30px;font-size:17px;font-weight:900;cursor:pointer}}
.davi-ok:hover{{opacity:.9}}
</style>
<div id="daviSuccessOverlay" class="davi-success-overlay">
  <div class="davi-success-card" role="dialog" aria-modal="true" aria-labelledby="daviSuccessTitle">
    <div id="daviSuccessTitle" class="davi-success-title">✅ Success! 🏫 {school_name}</div>
    <div class="davi-credentials">
      <div class="davi-label">👤 Username:</div>
      <div class="davi-value">{email}</div>
      <div class="davi-label">🔑 Password:</div>
      <div class="davi-value">{password}</div>
    </div>
    <button type="button" class="davi-ok" onclick="closeDaviSuccess()">OK ✅</button>
  </div>
</div>
<script>
function closeDaviSuccess(){
  const el=document.getElementById('daviSuccessOverlay');
  if(el) el.remove();
  try{history.replaceState({},document.title,'/schools/manage');}catch(e){}
}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeDaviSuccess();});
</script>
"""
                page = page.replace("</body>", success_prompt + "</body>", 1) if "</body>" in page else page + success_prompt
                return Response(
                    content=page,
                    status_code=response.status_code,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in ("content-length","content-type")},
                    media_type="text/html",
                )
            except Exception as exc:
                print("DAVISCHOOL SUCCESS PROMPT RENDER ERROR:", repr(exc), flush=True)

        # Restyle the existing code-sent panel to match the supplied design.
        if (
            path == "/schools/manage"
            and request.method.upper() == "GET"
            and request.query_params.get("success") == "code_sent"
            and request.query_params.get("pending_id")
            and response.status_code == 200
        ):
            try:
                import app.main as core
                con = core.get_db()
                pending = con.execute(
                    "SELECT * FROM pending_schools WHERE id=?",
                    (request.query_params.get("pending_id"),)
                ).fetchone()
                con.close()

                if pending:
                    school_name = str(pending["name"]).replace("<", "&lt;").replace(">", "&gt;")
                    email = str(pending["email"]).replace("<", "&lt;").replace(">", "&gt;")
                    code = str(pending["auth_code"])
                    spaced_code = " ".join(code)
                    pending_id = request.query_params.get("pending_id")

                    body = b""
                    async for chunk in response.body_iterator:
                        body += chunk
                    html = body.decode("utf-8")

                    script = f"""
<style>
.davi-code-banner{{margin-bottom:16px;background:#fff3c4;border:1.5px solid #fbbf24;border-radius:14px;padding:17px 22px;color:#92400e;font-size:20px}}
.davi-code-banner b{{font-size:20px}}
.davi-verify-panel{{margin-bottom:16px;background:#fffbeb;border:2px solid #f59e0b;border-radius:16px;padding:28px 30px}}
.davi-verify-title{{font-size:20px;font-weight:800;margin-bottom:24px}}
.davi-code-box{{border:2px dashed #f59e0b;border-radius:14px;background:white;padding:22px;text-align:center}}
.davi-code-label{{font-size:14px;font-weight:700;color:#92400e;margin-bottom:12px}}
.davi-code-value{{font-size:42px;font-weight:900;letter-spacing:11px;color:#0f172a}}
.davi-verify-row{{display:grid;grid-template-columns:1fr auto;gap:10px;margin-top:20px}}
.davi-code-input{{width:100%;box-sizing:border-box;padding:16px 18px;border:1px solid #fbbf24;border-radius:12px;text-align:center;font-size:21px;font-weight:800;letter-spacing:6px;outline:none}}
.davi-verify-btn{{background:#0f172a;color:white;padding:16px 22px;border:0;border-radius:12px;font-size:16px;font-weight:800;cursor:pointer;white-space:nowrap}}
.davi-verify-actions{{display:flex;gap:18px;margin-top:18px;font-size:14px}}
.davi-verify-actions a{{text-decoration:none;color:#64748b}}
@media(max-width:700px){{.davi-verify-row{{grid-template-columns:1fr}}.davi-code-value{{font-size:32px;letter-spacing:7px}}.davi-code-banner{{font-size:16px}}}}
</style>
<script>
document.addEventListener("DOMContentLoaded", function(){{
  const root = document.querySelector(".card");
  if (!root) return;
  const old = root.querySelector(":scope > div");
  if (!old) return;

  const banner = document.createElement("div");
  banner.className = "davi-code-banner";
  banner.innerHTML = "📧 <b>Code sent to {email}!</b> &nbsp; 🔒 Check inbox";

  const panel = document.createElement("div");
  panel.className = "davi-verify-panel";
  panel.innerHTML =
    '<div class="davi-verify-title">🔐 Enter Code for 🏫 {school_name}</div>' +
    '<div class="davi-code-box"><div class="davi-code-label">🔐 Your code:</div>' +
    '<div class="davi-code-value">{spaced_code}</div></div>' +
    '<form method="post" action="/verify-school-code">' +
    '<input type="hidden" name="pending_id" value="{pending_id}">' +
    '<div class="davi-verify-row"><input class="davi-code-input" name="auth_code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{{6}}" maxlength="6" required placeholder="🔢 Enter 6-digit code">' +
    '<button class="davi-verify-btn">✅ Verify &amp; Create Login</button></div></form>' +
    '<div class="davi-verify-actions"><a href="/schools/manage?success=code_sent&amp;pending_id={pending_id}">📧 Resend</a>' +
    '<a href="/schools/manage">❌ Cancel</a></div>';

  old.replaceWith(banner);
  root.insertBefore(panel, banner.nextSibling);
}});
</script>
"""
                    if "</body>" in html:
                        html = html.replace("</body>", script + "</body>", 1)
                    else:
                        html += script

                    return Response(
                        content=html,
                        status_code=response.status_code,
                        headers={k: v for k, v in response.headers.items()
                                 if k.lower() not in ("content-length", "content-type")},
                        media_type="text/html",
                    )
            except Exception as exc:
                print("DAVISCHOOL CODE PROMPT RENDER ERROR:", repr(exc), flush=True)

        return response
