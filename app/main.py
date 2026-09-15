#... keep everything same up to manage_schools, only this function changed...

@app.get("/schools/manage", response_class=HTMLResponse)
def manage_schools(request: Request, show: str = "", success: str = "", pending_id: str = "", new_pass: str = "", school_email: str = "", school_name: str = ""):
    if request.session.get("role")!= "super_admin": return RedirectResponse("/school/dashboard")
    name = request.session.get("name","")
    email = request.session.get("email","")
    initials = "".join([p[0] for p in name.split()][:2]).upper() if name else "DO"
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM schools ORDER BY id DESC")
    schools = cur.fetchall()
    cur.execute("SELECT * FROM users WHERE role='school_admin'")
    users = cur.fetchall()
    con.close()
    users_by_school = {u["school_id"]: u for u in users}
    success_banner = ""
    if success=="added":
        success_banner = f"""
        <div id='successBanner' style='background:#dcfce7; border:2px solid #16a34a; color:#166534; padding:16px; border-radius:10px; margin-bottom:16px'>
            <b>✅ Success! 🏫 School Added!</b>
            <div style='background:white; border:1px dashed #16a34a; border-radius:8px; padding:12px; margin-top:10px'>
                <div style='font-size:11px; color:#64748b'>🏫 School:</div><div style='font-weight:700'>{school_name}</div>
                <div style='font-size:11px; color:#64748b; margin-top:8px'>👤 Username (Email):</div><div style='font-weight:700; color:#0f172a'>{school_email}</div>
                <div style='font-size:11px; color:#64748b; margin-top:8px'>🔑 Password (Unique, active now):</div><div style='font-size:20px; font-weight:800; letter-spacing:1px; color:#0f172a'>{new_pass}</div>
            </div>
            <div style='margin-top:12px; text-align:right'>
                <button onclick="document.getElementById('successBanner').style.display='none'" style='background:#0f172a; color:white; padding:8px 18px; border:none; border-radius:8px; font-weight:600; cursor:pointer'>OK ✅</button>
            </div>
        </div>
        """
    elif success=="code_sent":
        success_banner = f"<div style='background:#fef3c7; border:1px solid #fcd34d; color:#92400e; padding:12px 16px; border-radius:10px; margin-bottom:16px'>📧 <b>Code sent to {SUPER_ADMIN}! 🔐</b> Check inbox or see code below.</div>"
    rows_html = ""
    schools_json = {}
    for s in schools:
        sid = s["id"]
        u = users_by_school.get(sid)
        upass = u["password"] if u else "—"
        uemail = u["email"] if u else s["email"]
        schools_json[sid] = {"id": sid, "name": s["name"], "email": s["email"], "code": s["code"], "location": s["location"], "phone": s["phone"] or "", "principal": s["principal"] or "", "school_type": s["school_type"] or "", "username": uemail, "password": upass}
        rows_html += f"""
        <tr id='row-{sid}' onclick='selectSchool({sid})' style='cursor:pointer; -webkit-user-select:none; user-select:none; caret-color:transparent;'>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:12px'><b>🏫 {s['name']}</b><div style='font-size:10px; color:#64748b'>🔑 {s['code']}</div></td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📧 {s['email']}</td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>📍 {s['location']}</td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'>👤 {uemail}</td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px'><span id='pwd-dot-{sid}'>••••••</span><span id='pwd-real-{sid}' style='display:none; font-weight:700'>{upass}</span> <span onclick="event.stopPropagation(); togglePwd({sid})" style='cursor:pointer; margin-left:6px; user-select:none;' tabindex='-1'>👁️</span></td>
            <td style='padding:10px; border-bottom:1px solid #eee; font-size:11px; text-align:center'>
                <span id='edit-{sid}' onclick="event.stopPropagation(); if(this.classList.contains('disabled')) return; editSchool({sid})" title='Click school row first' class='action-btn disabled' style='padding:5px 7px; background:#f1f5f9; border-radius:6px; margin-right:4px; cursor:not-allowed; opacity:0.3;'>✏️</span>
                <span id='del-{sid}' onclick="event.stopPropagation(); if(this.classList.contains('disabled')) return; confirmDelete({sid}, '{s['name']}')" title='Click school row first' class='action-btn disabled' style='padding:5px 7px; background:#fef2f2; border-radius:6px; cursor:not-allowed; opacity:0.3;'>🗑️</span>
            </td>
        </tr>
        """
    if not rows_html:
        rows_html = "<tr><td colspan=6 style='padding:24px; text-align:center; color:#999'>No schools yet 🏫</td></tr>"
    schools_data = json.dumps(schools_json)
    hl = "border:2px solid #0f172a; box-shadow:0 0 0 3px #e0f2fe" if show=="add" else "border:1px solid #e2e8f0"
    verify_html = ""
    if pending_id:
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT * FROM pending_schools WHERE id=?", (pending_id,))
        pending = cur.fetchone()
        con.close()
        if pending:
            code_display = f"<div style='background:white; border:2px dashed #f59e0b; border-radius:10px; padding:14px; margin-top:12px; text-align:center'><div style='font-size:11px; color:#92400e; font-weight:600'>🔓 Your code:</div><div style='font-size:32px; font-weight:800; letter-spacing:8px; color:#0f172a; margin-top:6px'>🔑 {pending['auth_code']}</div></div>"
            verify_html = f"<div style='background:#fffbeb; border:2px solid #f59e0b; border-radius:12px; padding:20px; margin-bottom:16px'><b>🔐 Enter Code for 🏫 {pending['name']}</b>{code_display}<form method='post' action='/verify-school-code' style='display:flex; gap:8px; margin-top:14px'><input type='hidden' name='pending_id' value='{pending_id}'><input name='auth_code' placeholder='🔢 Enter 6-digit code' required style='flex:1; padding:12px; border:1px solid #fcd34d; border-radius:8px; font-size:18px; letter-spacing:4px; text-align:center; font-weight:700'><button style='background:#0f172a; color:white; padding:12px 20px; border:none; border-radius:8px; font-weight:600'>✅ Verify & Create Login</button></form><div style='margin-top:8px; display:flex; gap:8px'><a href='/resend-code/{pending_id}' style='font-size:11px; color:#2563eb; text-decoration:none'>📧 Resend</a><a href='/schools/manage' style='font-size:11px; color:#64748b; text-decoration:none'>❌ Cancel</a></div></div>"
    return HTMLResponse(f"""
    <html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>*{{ caret-color: transparent; }} input, textarea {{ caret-color: auto!important; }}.no-caret{{ caret-color:transparent; user-select:none; -webkit-user-select:none; outline:none; }}.action-btn.disabled{{ opacity:0.3; cursor:not-allowed!important; pointer-events:none; }}.action-btn.active{{ opacity:1; cursor:pointer!important; pointer-events:auto; }}</style></head><body style='font-family:Arial; background:#f8fafc; margin:0'>{header_html(initials, name, email)}
    <div style='padding:20px; display:grid; grid-template-columns:1fr 380px; gap:16px; align-items:start'>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; overflow-x:auto' class='no-caret'>{success_banner}{verify_html}
            <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px'><div><b>📚 Registered Schools ({len(schools)})</b><div style='font-size:11px; color:#64748b'>👆 Click row to highlight 💙 → then ✏️ Edit / 🗑️ Delete becomes active</div></div></div>
            <table style='width:100%; border-collapse:collapse; min-width:800px' class='no-caret'><tr style='background:#f8fafc; font-size:11px; color:#64748b'><th style='padding:10px; text-align:left'>🏫 School</th><th style='padding:10px; text-align:left'>📧 Contact</th><th style='padding:10px; text-align:left'>📍 Location</th><th style='padding:10px; text-align:left'>👤 Username</th><th style='padding:10px; text-align:left'>🔑 Password</th><th style='padding:10px; text-align:center'>⚙️ Action</th></tr>{rows_html}</table>
        </div>
        <div style='background:white; {hl}; border-radius:12px; padding:20px; position:sticky; top:20px'><b>➕ Register New School 🏫</b><p style='font-size:11px; color:#64748b'>Unique password auto-created 🔑</p><form method='post' action='/register-school' style='display:flex; flex-direction:column; gap:10px; margin-top:12px'><input name='school_name' placeholder='🏫 School Name *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='school_email' placeholder='📧 Admin Email *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='location' placeholder='📍 Location *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='phone' placeholder='📱 Phone *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><input name='principal' placeholder='👨‍💼 Principal *' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><select name='school_type' required style='padding:11px; border:1px solid #e2e8f0; border-radius:8px'><option value=''>🎓 Type *</option><option>Primary</option><option>Secondary</option><option>Junior Secondary</option><option>Mixed</option><option>Private Academy</option></select><button style='background:#0f172a; color:white; padding:12px; border:none; border-radius:8px; font-weight:600'>📧 Send Code & Create Login</button><a href='/schools/manage' style='background:white; border:1px solid #e2e8f0; color:#64748b; padding:11px; border-radius:8px; text-align:center; text-decoration:none; font-size:13px; display:block'>❌ Cancel</a></form></div>
    </div>
    <script>
    let selectedId=null; let schools={schools_data};
    function selectSchool(id){{
        document.querySelectorAll('tr[id^="row-"]').forEach(r=>{{r.style.background='white';}});
        document.querySelectorAll('.action-btn').forEach(b=>{{b.classList.add('disabled'); b.classList.remove('active');}});
        document.getElementById('row-'+id).style.background='#dbeafe';
        document.getElementById('edit-'+id).classList.remove('disabled'); document.getElementById('edit-'+id).classList.add('active');
        document.getElementById('del-'+id).classList.remove('disabled'); document.getElementById('del-'+id).classList.add('active');
        selectedId=id;
    }}
    function togglePwd(id){{ let dot=document.getElementById('pwd-dot-'+id); let real=document.getElementById('pwd-real-'+id); if(dot.style.display==='none'){{ dot.style.display='inline'; real.style.display='none'; }} else {{ dot.style.display='none'; real.style.display='inline'; }} }}
    function confirmDelete(id, name){{
        if(confirm('🗑️ Confirm Deletion\\n\\nAre you sure you want to delete 🏫 ' + name + '?\\n\\nThis will remove school + login forever!')){{
            if(confirm('⚠️ Final confirm: Delete ' + name + ' permanently?')){{
                window.location='/schools/delete/' + id;
            }}
        }}
    }}
    function editSchool(id){{ alert('✏️ Edit ' + schools[id].name + ' — coming in edit modal (original system)'); }}
    </script>
    </body></html>
    """)
