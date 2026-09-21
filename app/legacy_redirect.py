from fastapi import Request
from fastapi.responses import RedirectResponse, Response, HTMLResponse, PlainTextResponse
from urllib.parse import quote

def install_legacy_school_redirect(app):
    """Disable legacy /school routes and decorate school verification responses."""
    @app.exception_handler(Exception)
    async def davischool_marks_exception_handler(request: Request, exc: Exception):
        # Keep the Marks Entry screen usable even when a legacy production
        # schema contains an unexpected column/table mismatch. This handler
        # is read-only: it never changes existing academic records.
        if request.url.path != "/app/academics/marks" or request.method.upper() != "GET":
            print("DAVISCHOOL UNHANDLED EXCEPTION:", repr(exc), flush=True)
            return PlainTextResponse("Internal Server Error", status_code=500)

        print("DAVISCHOOL MARKS PAGE EXCEPTION:", repr(exc), flush=True)
        try:
            import app.new_ui as ui
            sid = ui._school_session(request)
            if not sid:
                return RedirectResponse("/", status_code=303)
            if not ui._require_permission(request, sid, "marks.view"):
                return HTMLResponse("You do not have permission to view marks.", status_code=403)

            con = ui._db()
            cur = con.cursor()

            def safe_rows(sql, params=()):
                try:
                    return cur.execute(sql, params).fetchall()
                except Exception as inner:
                    print("DAVISCHOOL MARKS FALLBACK QUERY:", repr(inner), flush=True)
                    return []

            exams = safe_rows("SELECT id,name,term,year FROM exams WHERE school_id=? ORDER BY id DESC", (sid,))
            classes = safe_rows("SELECT id,name,stream FROM classes WHERE school_id=? ORDER BY name,stream", (sid,))
            subjects = safe_rows("SELECT id,name FROM subjects WHERE school_id=? ORDER BY name", (sid,))

            q = request.query_params
            exam_raw, class_raw, subject_raw = q.get("exam_id",""), q.get("class_id",""), q.get("subject_id","")
            eid = int(exam_raw) if exam_raw.isdigit() else (int(exams[0]["id"]) if exams else 0)
            cid = int(class_raw) if class_raw.isdigit() else 0
            subid = int(subject_raw) if subject_raw.isdigit() else 0

            students = []
            out_of = 100.0
            comments = {}
            marks_by_student = {}

            if eid and cid and subid:
                try:
                    students = cur.execute(
                        """SELECT id,admission_no,name FROM students
                           WHERE school_id=? AND class_id=? ORDER BY name""",
                        (sid, cid)
                    ).fetchall()
                except Exception as inner:
                    print("DAVISCHOOL MARKS STUDENT FALLBACK:", repr(inner), flush=True)
                    students = []

                try:
                    cfg = cur.execute(
                        "SELECT out_of FROM set_marks_config WHERE school_id=? AND exam_id=? AND subject_id=? ORDER BY id DESC LIMIT 1",
                        (sid, eid, subid)
                    ).fetchone()
                    if cfg and cfg["out_of"]:
                        out_of = float(cfg["out_of"])
                except Exception as inner:
                    print("DAVISCHOOL MARKS OUT-OF FALLBACK:", repr(inner), flush=True)

                for st in students:
                    try:
                        row = cur.execute(
                            "SELECT marks FROM marks WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=? ORDER BY id DESC LIMIT 1",
                            (sid, st["id"], eid, subid)
                        ).fetchone()
                        mark = row["marks"] if row else ""
                    except Exception as inner:
                        print("DAVISCHOOL MARKS VALUE FALLBACK:", repr(inner), flush=True)
                        mark = ""
                    try:
                        comments[int(st["id"])] = ""
                        row = cur.execute(
                            "SELECT comment FROM subject_performance_comments WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=? LIMIT 1",
                            (sid, st["id"], eid, subid)
                        ).fetchone()
                        if row:
                            comments[int(st["id"])] = str(row["comment"] or "")
                    except Exception:
                        pass
                    marks_by_student[int(st["id"])] = mark

            def opt(row, selected):
                rid = int(row["id"])
                label = str(row["name"] or "")
                stream = str(row["stream"] or "") if "stream" in row.keys() else ""
                if stream:
                    label += " " + stream
                return "<option value='%s' %s>%s</option>" % (
                    rid, "selected" if rid == selected else "", ui.escape(label)
                )

            eopts = "".join(opt(e, eid) for e in exams)
            copts = "".join(opt(c, cid) for c in classes)
            sopts = "".join(opt(s, subid) for s in subjects)

            rows = ""
            for st in students:
                mark = marks_by_student.get(int(st["id"]), "")
                if mark == "" or mark is None:
                    grade, points = "—", "—"
                else:
                    try:
                        grade, points = ui._subject_grade_points(cur, sid, subid, mark)
                        points = "%.1f" % float(points)
                    except Exception:
                        grade, points = ui._default_grade_points(float(mark))
                        points = "%.1f" % float(points)
                rows += (
                    "<tr><td>%s</td><td><b>%s</b></td>"
                    "<td><input id='recovery-mark-%s' name='mark_%s' value='%s' type='number' min='0' max='%s' step='0.01' class='markinput'></td>"
                    "<td>%s</td><td>%s</td>"
                    "<td><input name='comment_%s' value='%s' class='field' placeholder='Performance comment'></td>"
                    "<td style='white-space:nowrap'><button type='button' class='editbtn' onclick="document.getElementById('recovery-mark-%s').focus();document.getElementById('recovery-mark-%s').select();">✏️ Edit</button>"
                    "<button type='submit' formaction='/app/academics/marks/delete' formmethod='post' name='student_id' value='%s' class='deletebtn' onclick="return confirm('Delete this mark for %s? This cannot be undone.');">🗑️ Delete</button></td></tr>"
                    % (
                        ui.escape(str(st["admission_no"] or "")),
                        ui.escape(str(st["name"] or "")),
                        st["id"],
                        st["id"],
                        ui.escape(str(mark)),
                        out_of,
                        ui.escape(str(grade)),
                        points,
                        st["id"],
                        ui.escape(str(comments.get(int(st["id"]), ""))),
                        st["id"],
                        st["id"],
                        st["id"],
                        ui.escape(str(st["name"] or "")).replace("'", "&#39;")
                    )
                )

            body = (
                "<div class='page'><h1>Marks Entry</h1>"
                "<div class='muted'>Safe recovery view loaded. Existing records were not changed.</div>"
                "<div class='card section'><form method='get' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>"
                "<select name='exam_id' class='field'><option value=''>Select examination</option>%s</select>"
                "<select name='class_id' class='field'><option value=''>Select class</option>%s</select>"
                "<select name='subject_id' class='field'><option value=''>Select subject</option>%s</select>"
                "<button class='btn'>Load Students</button></form></div>"
                "<div class='card section'><form method='post' action='/app/academics/marks/save'>"
                "<input type='hidden' name='exam_id' value='%s'><input type='hidden' name='class_id' value='%s'><input type='hidden' name='subject_id' value='%s'>"
                "<table><thead><tr><th>Admission</th><th>Student</th><th>Mark / %s</th><th>Grade</th><th>Points</th><th>Performance Comment</th><th>Actions</th></tr></thead>"
                "<tbody>%s</tbody></table>%s</form></div></div>"
                "<style>.field{width:100%%;padding:11px;border:1px solid #dbe2ea;border-radius:9px;background:#fff}.markinput{width:100px;padding:8px;border:1px solid #dbe2ea;border-radius:8px}.editbtn,.deletebtn{padding:8px 11px;border:0;border-radius:8px;background:#111827;color:#fff;font-weight:800;cursor:pointer;margin-right:5px}.deletebtn{background:#b91c1c}.btn{padding:11px 16px;border:0;border-radius:9px;background:#111827;color:#fff;font-weight:800;cursor:pointer}</style>"
                % (
                    eopts, copts, sopts, eid, cid, subid, out_of,
                    rows or "<tr><td colspan='6'>Select an examination, class and subject, then load students.</td></tr>",
                    "<button class='btn' style='margin-top:12px'>Save Marks</button>" if students else ""
                )
            )
            con.close()
            return ui._school_page(request, "Marks Entry", body)
        except Exception as fallback_exc:
            print("DAVISCHOOL MARKS RECOVERY FAILED:", repr(fallback_exc), flush=True)
            return HTMLResponse(
                "<div style='font-family:Arial;padding:30px'><h2>Marks Entry could not be loaded</h2>"
                "<p>The system protected your existing records and did not change them.</p>"
                "<p>Please reload this page after the latest deployment completes.</p></div>",
                status_code=500
            )

    @app.middleware("http")
    async def redirect_legacy_school(request: Request, call_next):
        path = request.url.path

        # Legacy school URLs now go to the new application.
        if path == "/school" or path.startswith("/school/"):
            return RedirectResponse("/app", status_code=303)

        # IMPORTANT: do not handle /verify-school-code here.
        # This middleware runs outside SessionMiddleware, so request.session
        # is not available at this point. The real FastAPI route in main.py
        # handles verification after SessionMiddleware has run.
        response = await call_next(request)

        # Add the credential-success prompt after the core verification route.
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
                success_prompt = """
<style>
.davi-success-overlay{position:fixed;inset:0;background:rgba(15,23,42,.28);display:flex;align-items:center;justify-content:center;padding:20px;z-index:99999}
.davi-success-card{width:min(760px,96vw);background:#dcfce7;border:3px solid #16a34a;border-radius:18px;padding:28px;box-shadow:0 24px 70px rgba(15,23,42,.25);font-family:Arial,sans-serif}
.davi-success-title{font-size:25px;font-weight:900;color:#166534;margin-bottom:18px}
.davi-credentials{background:#fff;border:1.5px dashed #22c55e;border-radius:14px;padding:18px;margin-bottom:18px}
.davi-label{font-size:15px;color:#64748b;margin-top:8px}
.davi-value{font-size:25px;font-weight:900;color:#166534;word-break:break-word;margin-top:3px}
.davi-ok{display:block;margin-left:auto;background:#0f172a;color:white;border:0;border-radius:12px;padding:13px 30px;font-size:17px;font-weight:900;cursor:pointer}
</style>
<div id="daviSuccessOverlay" class="davi-success-overlay">
  <div class="davi-success-card" role="dialog" aria-modal="true">
    <div class="davi-success-title">SUCCESS! SCHOOL_NAME_PLACEHOLDER</div>
    <div class="davi-credentials">
      <div class="davi-label">👤 Username:</div>
      <div class="davi-value">EMAIL_PLACEHOLDER</div>
      <div class="davi-label">🔑 Password:</div>
      <div class="davi-value">PASSWORD_PLACEHOLDER</div>
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
""".replace("SCHOOL_NAME_PLACEHOLDER", school_name).replace("EMAIL_PLACEHOLDER", email).replace("PASSWORD_PLACEHOLDER", password)
                page = page.replace("</body>", success_prompt + "</body>", 1) if "</body>" in page else page + success_prompt
                return Response(content=page,status_code=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in ("content-length","content-type")},media_type="text/html")
            except Exception as exc:
                print("DAVISCHOOL SUCCESS PROMPT RENDER ERROR:", repr(exc), flush=True)

        # Restyle the code-sent panel without touching the verification POST.
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
                pending = con.execute("SELECT * FROM pending_schools WHERE id=?", (request.query_params.get("pending_id"),)).fetchone()
                con.close()
                if pending:
                    school_name = str(pending["name"]).replace("<", "&lt;").replace(">", "&gt;")
                    email = str(pending["email"]).replace("<", "&lt;").replace(">", "&gt;")
                    spaced_code = " ".join(str(pending["auth_code"]))
                    pending_id = request.query_params.get("pending_id")
                    body = b""
                    async for chunk in response.body_iterator:
                        body += chunk
                    html = body.decode("utf-8")
                    script = f"""
<style>
.davi-code-banner{{margin-bottom:16px;background:#fff3c4;border:1.5px solid #fbbf24;border-radius:14px;padding:17px 22px;color:#92400e;font-size:20px}}
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
@media(max-width:700px){{.davi-verify-row{{grid-template-columns:1fr}}.davi-code-value{{font-size:32px;letter-spacing:7px}}}}
</style>
<script>
document.addEventListener("DOMContentLoaded", function(){{
 const root=document.querySelector(".card"); if(!root)return;
 const old=root.querySelector(":scope > div"); if(!old)return;
 const banner=document.createElement("div"); banner.className="davi-code-banner"; banner.innerHTML="📧 <b>Code sent to {email}!</b> &nbsp; 🔒 Check inbox";
 const panel=document.createElement("div"); panel.className="davi-verify-panel";
 panel.innerHTML='<div class="davi-verify-title">🔐 Enter Code for 🏫 {school_name}</div><div class="davi-code-box"><div class="davi-code-label">🔐 Your code:</div><div class="davi-code-value">{spaced_code}</div></div><form method="post" action="/verify-school-code"><input type="hidden" name="pending_id" value="{pending_id}"><div class="davi-verify-row"><input class="davi-code-input" name="auth_code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{{6}}" maxlength="6" required placeholder="🔢 Enter 6-digit code"><button class="davi-verify-btn">✅ Verify &amp; Create Login</button></div></form><div class="davi-verify-actions"><a href="/schools/manage?success=code_sent&amp;pending_id={pending_id}">📧 Resend</a><a href="/schools/manage">❌ Cancel</a></div>';
 old.replaceWith(banner); root.insertBefore(panel,banner.nextSibling);
}});
</script>
"""
                    html=html.replace("</body>",script+"</body>",1) if "</body>" in html else html+script
                    return Response(content=html,status_code=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in ("content-length","content-type")},media_type="text/html")
            except Exception as exc:
                print("DAVISCHOOL CODE PROMPT RENDER ERROR:",repr(exc),flush=True)
        return response
