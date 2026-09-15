def layout(title, body, request, active="overview"):
    email = request.session.get("email", "")
    role = request.session.get("role", "")
    name = request.session.get("name", "Davis Ouma")
    school = get_user_school(request)

    if school:
        display_title = f"{school['name']} (Code: {school['code']})"
    else:
        display_title = title

    def nav_active(key):
        return "background:#0f172a; color:white; font-weight:600" if active==key else "color:#334155"
    sub_active = "background:white; border:1px solid #e2e8f0; box-shadow:0 1px 2px rgba(0,0,0,0.05); font-weight:600" if active=="overview" else "color:#475569"

    role_display = "Super Admin" if role=="super_admin" else "School Admin"
    initials = "".join([x[0] for x in name.split()][:2]).upper() if name else "DO"

    return f"""
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
*{{box-sizing:border-box}} body{{margin:0; font-family:Inter,Arial; background:#f8fafc; display:flex}}
.sidebar{{width:260px; background:white; border-right:1px solid #e2e8f0; height:100vh; position:fixed; overflow-y:auto}}
.logo{{padding:14px 16px; border-bottom:1px solid #e2e8f0; display:flex; gap:10px; align-items:center}}
.logo-icon{{width:36px; height:36px; background:#0f172a; color:white; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:16px}}
.nav-label{{font-size:10px; color:#94a3b8; margin:18px 16px 8px; letter-spacing:1px; font-weight:700}}
.nav-item{{display:flex; justify-content:space-between; align-items:center; padding:10px 12px; margin:2px 8px; border-radius:10px; text-decoration:none; font-size:13px; cursor:pointer}}
.sub-item{{display:flex; align-items:center; gap:8px; padding:8px 12px; margin:2px 8px 2px 24px; border-radius:8px; text-decoration:none; font-size:13px}}
.main{{margin-left:260px; flex:1}}.topbar{{background:white; border-bottom:1px solid #e2e8f0; padding:10px 20px; display:flex; justify-content:space-between; align-items:center; position:sticky; top:0; z-index:10}}
.content{{padding:24px}}.card{{background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px}}
.grid4{{display:grid; grid-template-columns:repeat(4,1fr); gap:16px}}.grid2{{display:grid; grid-template-columns:1fr 1fr; gap:16px}}
/* PROFILE DROPDOWN - FAR RIGHT EXACT LIKE SCREENSHOT */
.profile-wrapper{{position:relative; display:inline-block}}
.profile-btn{{display:flex; align-items:center; gap:8px; cursor:pointer; padding:4px 8px; border-radius:10px; user-select:none}}
.profile-btn:hover{{background:#f8fafc}}
.profile-avatar{{width:32px; height:32px; background:#e2e8f0; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:12px; color:#334155}}
.profile-dropdown{{position:absolute; right:0; top:48px; width:260px; background:white; border:1px solid #e2e8f0; border-radius:12px; box-shadow:0 8px 24px rgba(0,0,0,0.12); display:none; z-index:100; overflow:hidden}}
.profile-dropdown.show{{display:block}}
.dropdown-header{{padding:14px 16px; border-bottom:1px solid #f1f5f9}}
.dropdown-name{{font-weight:600; font-size:14px; color:#0f172a}}
.dropdown-email{{font-size:12px; color:#64748b; margin-top:2px; word-break:break-all}}
.dropdown-item{{display:flex; align-items:center; gap:10px; padding:12px 16px; text-decoration:none; color:#334155; font-size:13px; cursor:pointer}}
.dropdown-item:hover{{background:#f8fafc}}
.dropdown-item.logout{{color:#dc2626}}
.dropdown-divider{{height:1px; background:#f1f5f9; margin:4px 0}}
</style></head><body>
<div class='sidebar'>
<div class='logo'><div class='logo-icon'>D</div><div><b style='font-size:15px'>Davischool</b><div style='font-size:9px; color:#64748b'>SCHOOL MANAGEMENT SYSTEM</div></div></div>
<div class='nav-label'>Main Navigation</div>
<div class='nav-item' style='{nav_active("dashboard")}'><span style='display:flex; gap:8px; align-items:center'>📊 Dashboard</span><span style='font-size:10px'>^</span></div>
<a class='sub-item' href='/dashboard' style='{sub_active}'><span>🏠</span> System Overview</a>
<a class='sub-item' href='/dashboard?view=academic' style='color:#475569'><span>📊</span> Academic Analytics</a>
<a class='sub-item' href='/dashboard?view=financial' style='color:#475569'><span>📈</span> Financial Analytics</a>
<a class='sub-item' href='/attendance' style='color:#475569'><span>🗓️</span> Attendance Analysis</a>
<a class='nav-item' href='/students' style='color:#334155'><span>🎓 Students Manager</span><span>v</span></a>
<a class='nav-item' href='/staff' style='color:#334155'><span>👔 Staff Manager</span><span>v</span></a>
<a class='nav-item' href='/academic' style='color:#334155'><span>📚 Academic Manager</span><span>v</span></a>
<a class='nav-item' href='/timetable' style='color:#334155'><span>📅 Timetable</span><span>v</span></a>
<div style='position:absolute; bottom:0; width:100%; padding:12px; border-top:1px solid #e2e8f0; background:white'>
<div style='display:flex; gap:8px; align-items:center'><div style='width:32px; height:32px; background:#0f172a; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700'>{initials}</div><div><b style='font-size:12px'>{name}</b><br><small style='font-size:11px; color:#64748b'>{email[:22]}</small></div></div>
</div>
</div>
<div class='main'>
<div class='topbar'>
<div style='font-weight:700; font-size:14px'>{display_title}</div>
<div style='display:flex; align-items:center; gap:14px; font-size:14px'>
<span style='cursor:pointer; padding:6px; border-radius:8px'>▭</span>
<span style='cursor:pointer; padding:6px; border-radius:8px'>☀️</span>
<span style='cursor:pointer; padding:6px; border-radius:8px'>🔔</span>
<span style='cursor:pointer; padding:6px; border-radius:8px'>?</span>

<!-- PROFILE DROPDOWN - FAR RIGHT EXACT LIKE YOUR SCREENSHOT -->
<div class='profile-wrapper'>
<div class='profile-btn' onclick='toggleProfile()'>
<div class='profile-avatar'>{initials}</div>
<div style='text-align:left; line-height:1.2'><div style='font-size:13px; font-weight:600; color:#0f172a'>{name}</div><div style='font-size:11px; color:#64748b'>{role_display}</div></div>
<span style='font-size:10px; margin-left:4px'>⌄</span>
</div>
<div id='profileDropdown' class='profile-dropdown'>
<div class='dropdown-header'>
<div class='dropdown-name'>{name}</div>
<div class='dropdown-email'>{email}</div>
</div>
<a class='dropdown-item' href='/profile'><span>👤</span> Profile</a>
<a class='dropdown-item' href='/system-settings'><span>⚙️</span> Settings</a>
<div class='dropdown-divider'></div>
<a class='dropdown-item logout' href='/logout'><span>⎋</span> Log out</a>
</div>
</div>

</div>
</div>
{body}
</div>

<script>
function toggleProfile() {{
    document.getElementById('profileDropdown').classList.toggle('show');
}}
window.onclick = function(event) {{
    if (!event.target.closest('.profile-wrapper')) {{
        document.getElementById('profileDropdown').classList.remove('show');
    }}
}}
</script>

</body></html>
"""
