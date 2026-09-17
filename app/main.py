@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, tab: str = "personal"):
    if "email" not in request.session: return RedirectResponse("/")
    name = request.session.get("name","Davis Ouma"); email = request.session.get("email","oumadavis62@gmail.com")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    role = request.session.get("role","super_admin")

    # Get user details
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=?", (email,)); user_row = cur.fetchone()
    cur.execute("SELECT * FROM activity_log WHERE email=? ORDER BY id DESC LIMIT 20", (email,)); logs = cur.fetchall()
    con.close()

    phone = "+254748588874"
    org = "Davischool Platform"
    code = "SUPER-ADMIN" if role=="super_admin" else "SCHOOL-ADMIN"
    role_label = "Super Admin" if role=="super_admin" else "School Admin"

    active_personal = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="personal" else "color:#64748b"
    active_security = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="security" else "color:#64748b"
    active_log = "border-bottom:3px solid #0f172a; color:#0f172a; font-weight:800" if tab=="activity" else "color:#64748b"

    if tab == "personal":
        content_html = f"""
        <div style='display:grid; grid-template-columns:300px 1fr; gap:20px'>
          <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; text-align:center; height:fit-content'>
            <div style='width:80px; height:80px; background:#bfdbfe; color:#1e40af; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:900; font-size:28px; margin:0 auto 12px'>{initials}</div>
            <div style='font-weight:800; font-size:16px'>{name}</div>
            <div style='background:#e0f2fe; color:#0369a1; padding:4px 12px; border-radius:20px; font-size:11px; font-weight:700; display:inline-block; margin:6px 0'> {role_label} </div>
            <div style='font-size:12px; color:#64748b; margin-top:4px'>{email}</div>
            <div style='margin-top:18px; text-align:left; border-top:1px solid #f1f5f9; padding-top:14px'>
              <div style='font-weight:700; font-size:13px'>🏫 Davischool Platform</div>
              <div style='font-size:11px; color:#ec4899'>📍 Platform Owner</div>
              <div style='font-size:11px; color:#64748b; margin-top:10px'>🔑 Code: {code}</div>
            </div>
          </div>
          <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px'>
            <div style='font-weight:800; margin-bottom:16px'>👤 Personal Information</div>
            <form method='post' action='/profile/update'>
              <label style='font-size:11px; font-weight:700; color:#475569'>👤 Full Name</label>
              <input name='full_name' value="{name}" style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'>

              <label style='font-size:11px; font-weight:700; color:#475569'>📧 Email</label>
              <input value="{email}" disabled style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'>

              <label style='font-size:11px; font-weight:700; color:#475569'>📱 Phone</label>
              <input name='phone' value="{phone}" style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'>

              <label style='font-size:11px; font-weight:700; color:#475569'>🏫 Organization</label>
              <input value="{org}" disabled style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px; background:#f0f9ff'>

              <div style='text-align:right; margin-top:16px'>
                <button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:10px; font-weight:700; font-size:12px'>💾 Save Changes</button>
              </div>
            </form>
          </div>
        </div>
        """
    elif tab == "security":
        content_html = f"""
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; max-width:600px'>
          <div style='font-weight:800; margin-bottom:16px'>🔒 Security Settings</div>
          <form method='post' action='/profile/change-password'>
            <label style='font-size:11px; font-weight:700'>🔑 Current Password</label>
            <input type='password' name='current_pass' required placeholder='Enter current password' style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px'>
            <label style='font-size:11px; font-weight:700'>🔐 New Password</label>
            <input type='password' name='new_pass' required placeholder='Enter new password' style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px'>
            <label style='font-size:11px; font-weight:700'>✅ Confirm New Password</label>
            <input type='password' name='confirm_pass' required placeholder='Confirm new password' style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:10px; margin:4px 0 12px'>
            <button style='background:#0f172a; color:white; padding:11px 18px; border:none; border-radius:10px; font-weight:700; width:100%; margin-top:10px'>🔒 Update Password</button>
          </form>
          <div style='margin-top:20px; padding:14px; background:#fef2f2; border:1px solid #fecaca; border-radius:10px'>
            <div style='font-size:12px; font-weight:700; color:#991b1b'>⚠️ Danger Zone</div>
            <div style='font-size:11px; color:#7f1d1d; margin-top:4px'>Changing password will log you out on other devices</div>
          </div>
        </div>
        """
    else: # activity log
        log_rows = ""
        for l in logs:
            log_rows += f"<div style='padding:10px 12px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between'><div><span style='font-weight:700; font-size:12px'>{l['action']}</span><div style='font-size:11px; color:#64748b'>{l['details']}</div></div><div style='font-size:10px; color:#94a3b8'>{l['timestamp']}</div></div>"
        if not log_rows: log_rows = "<div style='padding:30px; text-align:center; color:#94a3b8'>No activity yet 📭</div>"
        content_html = f"""
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:0; overflow:hidden; max-width:800px'>
          <div style='padding:16px; font-weight:800; border-bottom:1px solid #f1f5f9'>📜 Activity Log - Last 20 actions</div>
          <div style='max-height:60vh; overflow:auto'>{log_rows}</div>
        </div>
        """

    return HTMLResponse(f"""
    <html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>body{{margin:0;font-family:Arial;background:#f8fafc}}</style></head>
    <body>
      {header_html(initials, name, email)}
      <div style='padding:20px; max-width:1100px; margin:auto'>
        <div style='margin-bottom:16px'><h2 style='margin:0; font-size:20px; display:flex; align-items:center; gap:8px'>👤 My Profile</h2></div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:0 16px; display:flex; gap:20px; margin-bottom:16px'>
          <a href='/profile?tab=personal' style='padding:12px 4px; text-decoration:none; font-size:13px; {active_personal}'>👤 Personal</a>
          <a href='/profile?tab=security' style='padding:12px 4px; text-decoration:none; font-size:13px; {active_security}'>🔒 Security</a>
          <a href='/profile?tab=activity' style='padding:12px 4px; text-decoration:none; font-size:13px; {active_log}'>📜 Activity Log</a>
        </div>
        {content_html}
      </div>
    </body></html>
    """)

@app.post("/profile/update")
def profile_update(request: Request, full_name: str = Form(...), phone: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session.get("email")
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET full_name=? WHERE email=?", (full_name, email))
    con.commit(); con.close()
    request.session["name"] = full_name
    log_activity(email, "✏️ Updated Profile", f"Name: {full_name}, Phone: {phone}")
    return RedirectResponse("/profile?tab=personal", status_code=303)

@app.post("/profile/change-password")
def change_password(request: Request, current_pass: str = Form(...), new_pass: str = Form(...), confirm_pass: str = Form(...)):
    if "email" not in request.session: return RedirectResponse("/")
    email = request.session.get("email")
    if new_pass!= confirm_pass: return HTMLResponse(f"❌ Passwords don't match <a href='/profile?tab=security'>Back</a>")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, current_pass)); u = cur.fetchone()
    if not u: con.close(); return HTMLResponse(f"❌ Wrong current password <a href='/profile?tab=security'>Back</a>")
    cur.execute("UPDATE users SET password=? WHERE email=?", (new_pass, email))
    con.commit(); con.close()
    log_activity(email, "🔒 Changed Password", "Password updated")
    return RedirectResponse("/profile?tab=security", status_code=303)
