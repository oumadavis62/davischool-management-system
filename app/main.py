@app.get("/academics", response_class=HTMLResponse)
def academics(request: Request, term: str = "Term 1", year: str = "2026", grade: str = "GRADE 7", tab: str = "performance"):
    if "school_id" not in request.session and request.session.get("role")!="super_admin": return RedirectResponse("/")
    is_super = request.session.get("role")=="super_admin" or request.session.get("user_email")==SUPER_ADMIN_EMAIL
    user_email = request.session.get("user_email", SUPER_ADMIN_EMAIL)
    role_display = "Super Admin" if is_super else "School Admin"
    school_name = request.session.get("school_name", "DaviSchool")
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT DISTINCT class FROM students WHERE school_id=?", (request.session.get("school_id",0),))
    classes_from_db = [r["class"] for r in cur.fetchall() if r["class"]]
    cur.execute("SELECT name FROM students WHERE school_id=? LIMIT 5", (request.session.get("school_id",0),))
    student_names = [r["name"] for r in cur.fetchall()]
    con.close()
    if not classes_from_db: classes_from_db = ["GRADE 7", "GRADE 8", "GRADE 9"]
    if not student_names: student_names = ["FLORENCE"]
    grades_options = "".join([f"<option value='{g}' {'selected' if g==grade else ''}>{g}</option>" for g in classes_from_db])
    students_badges = "".join([f"<span style='background:#f1f5f9; border:1px solid #e2e8f0; padding:4px 10px; border-radius:20px; font-size:12px; margin-right:6px'>{n.upper()} →</span>" for n in student_names[:3]])

    tab_links = f"""
        <div style='display:flex; gap:24px; border-bottom:1px solid #e2e8f0; margin-bottom:20px; font-size:14px'>
            <a href='/academics?term={term}&year={year}&grade={grade}&tab=performance' style='padding:10px 0; text-decoration:none; {"border-bottom:2px solid #0f172a; font-weight:600; color:#0f172a" if tab=="performance" else "color:#64748b"}'>📈 Performance Trends</a>
            <a href='/academics?term={term}&year={year}&grade={grade}&tab=subject' style='padding:10px 0; text-decoration:none; {"border-bottom:2px solid #0f172a; font-weight:600; color:#0f172a" if tab=="subject" else "color:#64748b"}'>📖 Subject Analysis</a>
            <a href='/academics?term={term}&year={year}&grade={grade}&tab=teacher' style='padding:10px 0; text-decoration:none; {"border-bottom:2px solid #0f172a; font-weight:600; color:#0f172a" if tab=="teacher" else "color:#64748b"}'>🎓 Teacher Performance</a>
            <a href='/academics?term={term}&year={year}&grade={grade}&tab=student' style='padding:10px 0; text-decoration:none; {"border-bottom:2px solid #0f172a; font-weight:600; color:#0f172a" if tab=="student" else "color:#64748b"}'>👥 Student Tracking</a>
        </div>
    """

    if tab == "subject":
        content_cards = f"""
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:20px; display:flex; gap:8px; align-items:center'>📊 Subject Performance Matrix</div>
            <div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'>
                <div style='font-size:36px; margin-bottom:12px'>📊</div><div style='font-size:14px'>No subject performance data available</div><div style='font-size:12px; margin-top:4px'>Term: {term} | Year: {year} | Grade: {grade}</div>
            </div>
        </div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:20px; display:flex; gap:8px; align-items:center'>👥 Gender Gap Analysis</div>
            <div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'>
                <div style='font-size:36px; margin-bottom:12px'>📊</div><div style='font-size:14px'>No gender gap data available</div>
            </div>
        </div>
        """
    elif tab == "teacher":
        content_cards = f"""
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:20px; display:flex; gap:8px; align-items:center'>📈 Top 10 Teachers by Value Added</div>
            <div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'>
                <div style='font-size:36px; margin-bottom:12px'>📊</div><div style='font-size:14px'>No teacher performance data available</div><div style='font-size:12px; margin-top:4px'>Term: {term} | Year: {year} | Grade: {grade}</div>
            </div>
        </div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:20px; display:flex; gap:8px; align-items:center'>🎓 Teacher Value-Added Details</div>
            <div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'>
                <div style='font-size:36px; margin-bottom:12px'>📊</div><div style='font-size:14px'>No teacher value-added data available</div>
            </div>
        </div>
        """
    elif tab == "student":
        content_cards = f"""
        <!-- Student Tracking Tab - YOUR NEW SCREENSHOTS -->
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:20px'>
                <div style='font-weight:600; display:flex; gap:8px; align-items:center'>👥 Student Trajectories</div>
                <label style='display:flex; align-items:center; gap:6px; font-size:12px; color:#64748b; border:1px solid #e2e8f0; padding:6px 12px; border-radius:20px; background:#f8fafc'>
                    <input type='checkbox'> ⚠️ Show At-Risk Only
                </label>
            </div>
            <div style='height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'>
                <div style='font-size:36px; margin-bottom:12px'>📊</div>
                <div style='font-size:14px'>No student trajectory data available</div>
            </div>
        </div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:12px; display:flex; gap:8px; align-items:center'>📈 Cohort Tracking</div>
            <div style='font-size:13px; color:#475569; margin-bottom:10px'>Select students to track their progression:</div>
            <div style='margin-bottom:20px'>{students_badges}</div>
            <div style='height:200px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'>
                <div style='font-size:36px; margin-bottom:12px'>📊</div>
                <div style='font-size:13px'>Select students above to view their progression chart</div>
            </div>
        </div>
        """
    else:
        content_cards = f"""
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:20px; display:flex; gap:8px; align-items:center'>📊 Class Performance Over Time</div>
            <div style='height:240px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8'>
                <div style='font-size:36px; margin-bottom:12px'>📊</div><div style='font-size:14px'>No exam data available for the selected filters</div><div style='font-size:12px; margin-top:4px'>Term: {term} | Year: {year} | Grade: {grade}</div>
            </div>
        </div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:16px; display:flex; gap:8px; align-items:center'>📈 Yearly Progression</div>
            <div style='position:relative; height:280px; padding-left:40px'>
                <div style='position:absolute; left:0; top:0; height:220px; display:flex; flex-direction:column; justify-content:space-between; font-size:12px; color:#94a3b8'><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
                <div style='height:220px; border-left:1px solid #cbd5e1; border-bottom:1px solid #cbd5e1; position:relative; display:flex; align-items:flex-end; justify-content:center'>
                    <div style='position:absolute; bottom:0; left:50%; transform:translateX(-50%); display:flex; flex-direction:column; align-items:center; gap:30px; height:220px; justify-content:flex-end; padding-bottom:20px'>
                        <div style='width:8px; height:8px; background:#22c55e; border-radius:50%'></div><div style='width:8px; height:8px; background:#3b82f6; border-radius:50%; margin-top:20px'></div><div style='width:8px; height:8px; background:#ef4444; border-radius:50%; margin-top:40px'></div>
                    </div>
                </div>
                <div style='text-align:center; font-size:12px; color:#64748b; margin-top:8px'>{year}</div>
                <div style='display:flex; justify-content:center; gap:20px; margin-top:12px; font-size:12px'>
                    <span style='display:flex; align-items:center; gap:6px'><span style='width:8px; height:8px; background:#3b82f6; border-radius:50%; display:inline-block'></span>Class Mean</span>
                    <span style='display:flex; align-items:center; gap:6px'><span style='width:8px; height:8px; background:#22c55e; border-radius:50%; display:inline-block'></span>Highest</span>
                    <span style='display:flex; align-items:center; gap:6px'><span style='width:8px; height:8px; background:#ef4444; border-radius:50%; display:inline-block'></span>Lowest</span>
                </div>
            </div>
        </div>
        <div style='background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:20px'>
            <div style='font-weight:600; margin-bottom:16px; display:flex; gap:8px; align-items:center'>📖 Subject Trends Across Terms</div>
            <div style='position:relative; height:340px; padding-left:40px'>
                <div style='position:absolute; left:0; top:0; height:220px; display:flex; flex-direction:column; justify-content:space-between; font-size:12px; color:#94a3b8'><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
                <div style='height:220px; border-left:1px solid #cbd5e1; border-bottom:1px solid #cbd5e1; position:relative;'>
                    <div style='position:absolute; bottom:20px; left:50%; transform:translateX(-50%); display:flex; flex-direction:column; gap:8px; align-items:center'>
                        <div style='width:6px; height:6px; background:#ef4444; border-radius:50%'></div><div style='width:6px; height:6px; background:#22c55e; border-radius:50%'></div><div style='width:6px; height:6px; background:#3b82f6; border-radius:50%'></div><div style='width:6px; height:6px; background:#f59e0b; border-radius:50%'></div><div style='width:6px; height:6px; background:#ef4444; border-radius:50%'></div><div style='width:6px; height:6px; background:#8b5cf6; border-radius:50%'></div><div style='width:6px; height:6px; background:#06b6d4; border-radius:50%'></div><div style='width:6px; height:6px; background:#22c55e; border-radius:50%'></div><div style='width:6px; height:6px; background:#3b82f6; border-radius:50%'></div><div style='width:6px; height:6px; background:#3b82f6; border-radius:50%'></div>
                    </div>
                </div>
                <div style='text-align:center; font-size:11px; color:#64748b; margin-top:8px'>T3 2026</div>
                <div style='display:flex; flex-wrap:wrap; gap:12px; justify-content:center; margin-top:14px; font-size:11px; line-height:1.6'>
                    <span style='color:#0ea5e9'>◉ AGRICULTURE</span><span style='color:#22c55e'>◉ CHRISTIAN_RELIGIOUS_EDUCATION</span><span style='color:#ef4444'>◉ CREATIVE_ARTS</span><span style='color:#f59e0b'>◉ ENGLISH</span>
                    <span style='color:#06b6d4'>◉ INTERGRATED_SCIENCE</span><span style='color:#8b5cf6'>◉ KISWAHILI</span><span style='color:#ec4899'>◉ MATHEMATICS</span><span style='color:#84cc16'>◉ PRE-TECHNICAL_STUDIES</span><span style='color:#f97316'>◉ SOCIAL_STUDIES</span>
                </div>
            </div>
        </div>
        """

    body=f"""
    <div class='content'>
        <h1 style='font-size:26px; font-weight:700'>Academic Analytics</h1>
        <div style='color:#64748b; font-size:14px; margin:6px 0 18px'>Performance insights across subjects, teachers, and students</div>
        <div style='display:flex; gap:12px; margin-bottom:20px'>
            <select id='termSel' style='padding:10px 14px; border:1px solid #e2e8f0; border-radius:10px; background:white; min-width:120px' onchange="updateFilters()">
                <option {'selected' if term=='Term 1' else ''}>Term 1</option><option {'selected' if term=='Term 2' else ''}>Term 2</option><option {'selected' if term=='Term 3' else ''}>Term 3</option>
            </select>
            <select id='yearSel' style='padding:10px 14px; border:1px solid #e2e8f0; border-radius:10px; background:white; min-width:120px' onchange="updateFilters()">
                <option {'selected' if year=='2024' else ''}>2024</option><option {'selected' if year=='2025' else ''}>2025</option><option {'selected' if year=='2026' else ''}>2026</option>
            </select>
            <select id='gradeSel' style='padding:10px 14px; border:1px solid #e2e8f0; border-radius:10px; background:white; min-width:140px' onchange="updateFilters()">
                {grades_options}
            </select>
        </div>
        {tab_links}
        {content_cards}
    </div>
    <script>
    function updateFilters(){{
        var t=document.getElementById('termSel').value;
        var y=document.getElementById('yearSel').value;
        var g=document.getElementById('gradeSel').value;
        var currentTab='{tab}';
        window.location='/academics?term='+encodeURIComponent(t)+'&year='+encodeURIComponent(y)+'&grade='+encodeURIComponent(g)+'&tab='+currentTab;
    }}
    </script>
    """
    return HTMLResponse(wrap(school_name, body, user_email, role_display, "academics"))
