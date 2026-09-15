@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "personal"):
    if "email" not in request.session:
        return RedirectResponse("/")

    email = request.session.get("email","")
    name = request.session.get("name","Davis Ouma")
    school = get_school(request)
    is_super = school is None

    if is_super:
        top = "Davischool Platform (Super Admin)"
        sname = "Davischool Platform"
        scode = "SUPER-ADMIN"
        sloc = "Platform Owner - Full System Control"
        badge = "Super Admin"
        bstyle = "background:#0f172a; color:white"
    else:
        top = f"{school['name']} (Code: {school['code']})"
        sname = school['name']
        scode = school['code']
        sloc = school['location']
        badge = "School Admin"
        bstyle = "background:#e0f2fe; color:#0369a1; border:1px solid #bae6fd"

    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "SA"

    # Tab active styles
    def tab_style(key):
        if tab==key:
            return "border-bottom:2px solid #0f172a; color:#0f172a; font-weight:700"
        return "color:#64748b"

    # Content for each tab
    if tab=="security":
        right_content = f"""
        <b>Security Settings</b><p style='font-size:11px; color:#64748b'>Manage your password and security</p>
        <label style='font-size:12px; font-weight:600; margin-top:16px; display:block'>Current Password</label><input type='password' placeholder='Enter current password' style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:6px'>
        <label style='font-size:12px; font-weight:600; margin-top:12px; display:block'>New Password</label><input type='password' placeholder='Enter new password' style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:6px'>
        <label style='font-size:12px; font-weight:600; margin-top:12px; display:block'>Confirm New Password</label><input type='password' placeholder='Confirm new password' style='width:100%; padding:11px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; margin-top:6px'>
        <div style='margin-top:18px; text-align:right'><button style='background:#0f172a; color:white; padding:10px 18px; border:none; border-radius:8px; font-size:12px'>Update Password</button></div>
        """
    elif tab=="activity":
        right_content = f"""
        <b>Activity Log</b><p style='font-size:11px; color:#64748b'>Your recent account activity</p>
        <div style='margin-top:16px; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden'>
        <div style='padding:12px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between; font-size:12px'><span>✅ Logged in - {email}</span><span style='color:#64748b'>Today 6:23 PM</span></div>
        <div style='padding:12px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between; font-size:12px'><span>👤 Profile viewed - {sname}</span><span style='color:#64748b'>Today 6:20 PM</span></div>
        <div style='padding:12px; display:flex; justify-content:space-between; font-size:12px'><span>🔐 Password changed</span><span style='color:#64748b'>Yesterday</span></div>
        </div>
        """
    else: # personal info tab - EXACT LIKE YOUR PICTURE
        right_content = f"""
        <b>Personal Information</b><p style='font-size:11px; color:#64748b; margin-top:2px'>Update your name, email, and phone number</p>
        <label style='font-size:12px; font-weight:600; margin-top:16px; display:block'>Full Name</label>
        <div style='position:relative; margin-top:6px'><span style='position:absolute; left:10px; top:11px; font-size:12px; color:#64748b'>👤</span><input value='{name}' style='width:100%; padding:11px 11px 11px 34px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; font-size:13px'></div>
        <label style='font-size:12px; font-weight:600; margin-top:14px; display:block'>Email Address</label>
        <div style='position:relative; margin-top:6px'><span style='position:absolute; left:10px; top:11px; font-size:12px; color:#64748b'>✉️</span><input value='{email}' style='width:100%; padding:11px 11px 11px 34px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; font-size:13px'></div>
        <label style='font-size:12px; font-weight:600; margin-top:14px; display:block'>Phone Number</label>
        <div style='position:relative; margin-top:6px'><span style='position:absolute; left:10px; top:11px; font-size:12px; color:#64748b'>📞</span><input value='+254748588874' style='width:100%; padding:11px 11px 11px 34px; border:1px solid #e2e8f0; border-radius:8px; background:#f8fafc; font-size:13px'></div>
        <div style='margin-top:20px; text-align:right'><button style='background:#0f172a; color:white; padding:11px 20px; border:none; border-radius:8px; font-size:13px; font-weight:600'>Save Changes</button></div>
        """

    html = f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
body{{margin:0; font-family:Inter,Arial; background:#f8fafc}}
.top{{background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center}}
.content{{padding:20px}}
.card{{background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px}}
.grid{{display:grid; grid-template-columns:360px 1fr; gap:16px}}
.big{{width:84px; height:84px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:28px; font-weight:800; margin:0 auto; position:relative}}
.tab{{display:inline-flex; gap:6px; align-items:center; padding:8px 4px 10px; margin-right:20px; text-decoration:none; font-size:13px; border-bottom:2px solid transparent; cursor:pointer}}
</style></head><body>
<div class='top'><div style='font-weight:700; font-size:14px'>{top}</div><div style='display:flex; gap:10px; font-size:12px'><a href='/dashboard' style='text-decoration:none; color:#64748b'>Dashboard</a> <a href='/logout' style='color:#dc2626; text-decoration:none'>Logout</a></div></div>

<div class='content'>
<div style='margin-bottom:14px'><div style='font-size:18px; font-weight:800'>My Profile</div><div style='font-size:12px; color:#64748b; margin-top:2px'>Manage your personal information and security settings</div></div>

<div style='display:flex; border-bottom:1px solid #e2e8f0; margin-bottom:16px; padding-bottom:0px'>
<a href='/profile?tab=personal' class='tab' style='{tab_style("personal")}'>👤 Personal Info</a>
<a href='/profile?tab=security' class='tab' style='{tab_style("security")}'>🔒 Security</a>
<a href='/profile?tab=activity' class='tab' style='{tab_style("activity")}'>📈 Activity Log</a>
</div>

<div class='grid'>
<div class='card' style='text-align:center; height:fit-content'>
<div class='big'>{initials}<span style='position:absolute; bottom:2px; right:2px; width:22px; height:22px; background:white; border-radius:50%; border:1px solid #e2e8f0; display:flex; align-items:center; justify-content:center; font-size:10px'>📷</span></div>
<div style='font-weight:700; margin-top:14px; font-size:15px'>{name}</div>
<div style='margin-top:8px'><span style='padding:4px 10px; border-radius:20px; font-size:11px; font-weight:700; {bstyle}'>{badge}</span></div>
<div style='margin-top:12px; font-size:12px; color:#334155; display:flex; gap:6px; justify-content:center; align-items:center'>✉️ {email}</div>
<div style='margin-top:14px; border-top:1px solid #f1f5f9; padding-top:12px'><div style='font-size:12px; font-weight:600; color:#334155'>{sname}</div><div style='font-size:11px; color:#64748b; margin-top:2px'>{sloc}</div><div style='font-size:10px; color:#94a3b8; margin-top:2px'>Code: {scode}</div></div>
<div style='margin-top:12px; font-size:10px; color:#16a34a; background:#f0fdf4; border:1px solid #bbf7d0; padding:6px; border-radius:6px'>✅ Dynamic - {sname} sees own data</div>
</div>

<div class='card'>
{right_content}
</div>
</div>
</div>
</body></html>
"""
    return HTMLResponse(html)
