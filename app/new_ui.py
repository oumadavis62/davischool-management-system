from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def davischool_login_page(request: Request):
    if request.session.get("email"):
        return RedirectResponse("/app", status_code=303)
    return HTMLResponse("""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>DaviSchool Login</title><style>body{margin:0;background:#f4f7fb;font-family:Arial,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center}.box{width:min(430px,92vw);background:white;border:1px solid #e2e8f0;border-radius:18px;padding:32px;box-shadow:0 18px 50px #0f172a14}.logo{font-size:25px;font-weight:900;color:#111827;margin-bottom:5px}.sub{color:#64748b;margin-bottom:25px}label{display:block;font-size:13px;font-weight:800;color:#334155;margin:14px 0 7px}input{width:100%;box-sizing:border-box;padding:13px;border:1px solid #dbe2ea;border-radius:10px;font-size:15px}button{width:100%;margin-top:20px;padding:14px;border:0;border-radius:10px;background:#111827;color:white;font-weight:900;font-size:15px;cursor:pointer}.err{background:#fff1f2;border:1px solid #fda4af;color:#9f1239;padding:11px;border-radius:10px;margin-bottom:14px}</style></head><body><div class='box'><div class='logo'>🏫 DaviSchool Management System</div><div class='sub'>Secure school management platform</div>{%ERROR%}<form method='post' action='/login'><label>Email / Username</label><input name='email' type='email' autocomplete='username' required placeholder='Enter your email'><label>Password</label><input name='password' type='password' autocomplete='current-password' required placeholder='Enter password'><button type='submit'>Sign In</button></form></div></body></html>""".replace("{%ERROR%}", "<div class='err'>Invalid username or password.</div>" if request.query_params.get("error") else ""))

@router.post("/login")
def davischool_login(request: Request, email: str = Form(...), password: str = Form(...)):
    from app.main import verify_password
    con = _db()
    try:
        user = con.execute("SELECT * FROM users WHERE lower(email)=lower(?) LIMIT 1", (email.strip(),)).fetchone()
    finally:
        con.close()
    if not user:
        return RedirectResponse("/?error=1", status_code=303)
    ok, legacy = verify_password(password, user["password"] or "")
    if not ok:
        return RedirectResponse("/?error=1", status_code=303)
    request.session["email"] = user["email"]
    request.session["role"] = user["role"]
    request.session["school_id"] = user["school_id"]
    request.session["name"] = user["full_name"] or user["email"]
    # Transparently upgrade any legacy plaintext password after a successful login.
    if legacy:
        from app.main import hash_password
        con = _db()
        con.execute("UPDATE users SET password=? WHERE id=?", (hash_password(password), user["id"]))
        con.commit(); con.close()
    return RedirectResponse("/app", status_code=303)

@router.get("/logout")
def davischool_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)

def _db():
    from app.main import get_db
    return get_db()

def _shell(title, name, role, body):
    # Keep the sidebar aligned with the authenticated workspace.
    # Super Admin users must not be offered school-scoped pages because those
    # pages intentionally require a school_id and would otherwise redirect
    # back to the login page.
    if role == "super_admin":
        nav = [
            ("/app","⌂","Platform Overview"),