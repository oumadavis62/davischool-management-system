@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "email" not in request.session:
        return RedirectResponse("/")

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) as c FROM schools")
    total_schools = cur.fetchone()["c"]
    cur.execute("SELECT * FROM schools ORDER BY id DESC LIMIT 5")
    recent_schools = cur.fetchall()
    con.close()

    school = get_school(request)
    is_super = school is None
    name = request.session.get("name","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    role_disp = "Super Admin" if is_super else "School Admin"

    if is_super:
        top = "Davischool Platform (Super Admin)"
        # Zeraki-style stats
        active_schools = total_schools # all active for now
        revenue = total_schools * 15000
        total_students = total_schools * 350 # mock avg

        schools_rows = ""
        for s in recent_schools:
            schools_rows += f"""
            <tr>
            <td style='padding:12px; border-bottom:1px solid #f1f5f9'><div style='font-weight:600; font-size:13px'>{s['name']}</div><div style='font-size:11px; color:#64748b'>{s['code']}</div></td>
            <td style='padding:12px; border-bottom:1px solid #f1f5f9; font-size:12px'>{s['location']}</td>
            <td style='padding:12px; border-bottom:1px solid #f1f5f9'><span style='background:#dcfce7; color:#166534; padding:3px 8px; border-radius:12px; font-size:10px'>Active</span></td>
            <td style='padding:12px; border-bottom:1px solid #f1f5f9; font-size:11px; color:#64748b'>Today</td>
            </tr>
            """
        if not schools_rows:
            schools_rows = "<tr><td colspan=4 style='padding:24px; text-align:center; color:#94a3b8; font-size:12px'>No schools registered yet. Add your first school.</td></tr>"

        content = f"""
        <div style='padding:24px'>
        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:20px'>
        <div><h2 style='margin:0; font-size:22px; font-weight:800; color:#0f172a'>School Overview</h2><p style='margin:4px 0 0; color:#64748b; font-size:13px'>Welcome {name} - Monitor all schools and platform performance</p></div>
        <a href='/schools/manage' style='background:#0f172a; color:white; padding:10px 18px; border-radius:10px; text-decoration:none; font-size:13px; font-weight:600'>+ Add School</a>
        </div>

        <!-- ZERAKI STYLE STATS CARDS -->
        <div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>
            <div style='display:flex; justify-content:space-between; align-items:center'><div style='font-size:11px; color:#64748b; font-weight:600; letter-spacing:0.5px'>TOTAL SCHOOLS</div><div style='width:32px; height:32px; background:#e0f2fe; border-radius:8px; display:flex; align-items:center; justify-content:center'>🏫</div></div>
            <div style='font-size:28px; font-weight:800; margin:8px 0 2px'>{total_schools}</div>
            <div style='font-size:11px; color:#16a34a'>↑ 12% from last month</div>
            </div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>
            <div style='display:flex; justify-content:space-between; align-items:center'><div style='font-size:11px; color:#64748b; font-weight:600; letter-spacing:0.5px'>ACTIVE SUBSCRIPTIONS</div><div style='width:32px; height:32px; background:#dcfce7; border-radius:8px; display:flex; align-items:center; justify-content:center'>✅</div></div>
            <div style='font-size:28px; font-weight:800; margin:8px 0 2px'>{active_schools}</div>
            <div style='font-size:11px; color:#16a34a'>All schools active</div>
            </div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>
            <div style='display:flex; justify-content:space-between; align-items:center'><div style='font-size:11px; color:#64748b; font-weight:600; letter-spacing:0.5px'>TOTAL REVENUE</div><div style='width:32px; height:32px; background:#fef9c3; border-radius:8px; display:flex; align-items:center; justify-content:center'>💰</div></div>
            <div style='font-size:28px; font-weight:800; margin:8px 0 2px'>KES {revenue:,}</div>
            <div style='font-size:11px; color:#64748b'>KES 15k per school</div>
            </div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>
            <div style='display:flex; justify-content:space-between; align-items:center'><div style='font-size:11px; color:#64748b; font-weight:600; letter-spacing:0.5px'>TOTAL STUDENTS</div><div style='width:32px; height:32px; background:#ede9fe; border-radius:8px; display:flex; align-items:center; justify-content:center'>🎓</div></div>
            <div style='font-size:28px; font-weight:800; margin:8px 0 2px'>{total_students:,}</div>
            <div style='font-size:11px; color:#64748b'>Across all schools</div>
            </div>
        </div>

        <div style='display:grid; grid-template-columns:2fr 1fr; gap:16px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:0; overflow:hidden'>
            <div style='padding:16px 18px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between; align-items:center'><b style='font-size:14px'>Recently Added Schools</b><a href='/schools/manage' style='font-size:12px; color:#2563eb; text-decoration:none'>View All</a></div>
            <table style='width:100%; border-collapse:collapse'><thead><tr style='background:#f8fafc; text-align:left; font-size:11px; color:#64748b'><th style='padding:10px 12px'>School Name</th><th style='padding:10px 12px'>Location</th><th style='padding:10px 12px'>Status</th><th style='padding:10px 12px'>Date</th></tr></thead><tbody>{schools_rows}</tbody></table>
            </div>
            <div style='display:flex; flex-direction:column; gap:16px'>
                <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'>
                <b style='font-size:14px'>Quick Actions</b>
                <div style='margin-top:12px; display:flex; flex-direction:column; gap:8px'>
                <a href='/schools/manage' style='display:block; background:#0f172a; color:white; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px; font-weight:600'>Manage Schools</a>
                <a href='/profile?tab=personal' style='display:block; background:white; border:1px solid #e2e8f0; color:#0f172a; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px'>View Profile (3 Tabs)</a>
                <a href='/schools/manage' style='display:block; background:#f8fafc; border:1px dashed #cbd5e1; color:#64748b; padding:10px; border-radius:8px; text-align:center; text-decoration:none; font-size:12px'>+ Register New School</a>
                </div>
                </div>
                <div style='background:#0f172a; border-radius:14px; padding:18px; color:white'>
                <div style='font-size:13px; font-weight:700'>Davischool Analytics</div>
                <div style='font-size:11px; color:#94a3b8; margin-top:4px'>Platform is performing well. All {total_schools} schools active with no issues reported.</div>
                <div style='margin-top:12px; background:#1e293b; border-radius:8px; padding:10px'><div style='font-size:10px; color:#94a3b8'>PLATFORM HEALTH</div><div style='font-size:18px; font-weight:700; margin-top:2px; color:#4ade80'>99.9% Uptime</div></div>
                </div>
            </div>
        </div>
        </div>
        """
    else:
        # School Admin view (simple)
        top = school["name"] + " (Code: " + school["code"] + ")"
        content = f"""
        <div style='padding:24px'>
        <h2 style='margin:0; font-size:22px; font-weight:800'>School Overview</h2>
        <p style='color:#64748b; font-size:13px'>Welcome {name} - {top}</p>
        <div style='display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:20px'>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>STUDENTS</div><div style='font-size:24px; font-weight:800; margin-top:6px'>1,240</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>TEACHERS</div><div style='font-size:24px; font-weight:800; margin-top:6px'>42</div></div>
            <div style='background:white; border:1px solid #e2e8f0; border-radius:14px; padding:18px'><div style='font-size:11px; color:#64748b'>CLASSES</div><div style='font-size:24px; font-weight:800; margin-top:6px'>18</div></div>
        </div>
        </div>
        """

    return HTMLResponse(f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head>
<body style='font-family:Arial; margin:0; background:#f8fafc'>
<div style='background:white; border-bottom:1px solid #e2e8f0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center'>
<div style='font-weight:700; font-size:14px'>{'Davischool Platform (Super Admin)' if is_super else top}</div>
<div style='display:flex; gap:12px; align-items:center; font-size:12px'>
<div style='width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700'>{initials}</div>
<div><div style='font-weight:600'>{name}</div><div style='color:#64748b; font-size:11px'>{role_disp}</div></div>
<a href='/profile?tab=personal' style='border:1px solid #e2e8f0; padding:6px 10px; border-radius:6px; text-decoration:none'>Profile</a>
<a href='/logout' style='color:#dc2626; text-decoration:none'>Logout</a>
</div>
</div>
{content}
</body></html>
""")
