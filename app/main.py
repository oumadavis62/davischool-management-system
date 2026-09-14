import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
DB="school.db"
app=FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davi-secret-2026")
def init_db():
    con=sqlite3.connect(DB); c=con.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, adm TEXT UNIQUE, name TEXT, class TEXT, stream TEXT, gender TEXT, kcpe INTEGER, school TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, tsc TEXT UNIQUE, name TEXT, subject TEXT, phone TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, adm TEXT, term TEXT, year TEXT, subject TEXT, score INTEGER, grade TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, adm TEXT, amount INTEGER, balance INTEGER, term TEXT, year TEXT, date TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, code TEXT, box TEXT, phone TEXT, email TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)")
    c.execute("INSERT OR IGNORE INTO users VALUES (1,'admin','Ouma@940','admin')")
    con.commit(); con.close()
init_db()
def get_db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; return con
def layout(title, body, user="admin", school="DAVISCHOOL - School Management System"):
    return f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} - DAVISCHOOL</title><style>*{{box-sizing:border-box;font-family:'Segoe UI',Arial}}body{{margin:0;background:#f5f7fb;display:flex;min-height:100vh}}.sidebar{{width:280px;background:#f0f6ff;border-right:1px solid #e2e8f0;position:fixed;height:100vh;overflow-y:auto;padding:0 10px}}.main{{margin-left:280px;flex:1}}.topbar{{background:#fff;border-bottom:1px solid #e2e8f0;padding:14px 24px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:10}}.logo{{display:flex;align-items:center;gap:10px;padding:18px 12px;border-bottom:1px solid #e2e8f0;margin:0 -10px 10px -10px;background:#fff}}.logo-icon{{width:44px;height:44px;background:#e0f2fe;border:2px solid #0ea5e9;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:900;color:#0ea5e9;font-size:20px}}.nav-title{{font-size:11px;color:#64748b;font-weight:700;padding:10px 12px;margin-top:10px;text-transform:uppercase}}.nav-item{{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-radius:8px;cursor:pointer;color:#334155;font-size:14px}}.nav-item:hover{{background:#e0f2fe}}.submenu{{display:none;padding-left:20px;margin:4px 0}}.submenu.open{{display:block}}.submenu a{{display:flex;align-items:center;gap:8px;padding:8px 12px;color:#475569;text-decoration:none;font-size:13px;border-radius:6px}}.submenu a:hover{{background:#fff;color:#0ea5e9}}.content{{padding:20px 24px}}.card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:18px;margin-bottom:18px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px 12px;border:1px solid #e2e8f0;text-align:left;font-size:13px}}th{{background:#f8fafc}}.btn{{padding:8px 14px;border-radius:8px;border:none;cursor:pointer;text-decoration:none;display:inline-block;font-size:13px}}.btn-primary{{background:#0f172a;color:#fff}}.user-box{{padding:12px;border-top:1px solid #e2e8f0;margin-top:10px;display:flex;align-items:center;gap:10px}}.user-avatar{{width:32px;height:32px;background:#0f172a;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px}}input,select{{padding:9px 12px;border:1px solid #cbd5e1;border-radius:8px;width:100%}}</style></head><body><div class="sidebar"><div class="logo"><div class="logo-icon">D</div><div><b>DAVISCHOOL</b><br><span style="font-size:10px;color:#64748b">SCHOOL MANAGEMENT</span></div></div><div class="nav-title">Main Navigation</div><div class="nav-item" onclick="toggle('dash')"><span>📊 Dashboard</span><span>⌄</span></div><div id="dash" class="submenu"><a href="/dashboard">Overview</a></div><div class="nav-item" onclick="toggle('stud')"><span>🎓 Students Manager</span><span>⌄</span></div><div id="stud" class="submenu"><a href="/students">Students List</a><a href="/classes">Class List</a></div><div class="nav-item" onclick="toggle('staff')"><span>👥 Staff Manager</span><span>⌄</span></div><div id="staff" class="submenu"><a href="/teachers">Staff List</a></div><div class="nav-item" onclick="toggle('acad')"><span>📖 Academic Manager</span><span>⌄</span></div><div id="acad" class="submenu open"><a href="/marks">Record Marks</a><a href="/reports">Exam Analysis</a></div><div class="nav-item" onclick="toggle('fin')"><span>💰 Finance</span><span>⌄</span></div><div id="fin" class="submenu"><a href="/fees">Fees</a></div><div class="nav-item" onclick="toggle('sys')"><span>⚙️ System Settings</span><span>⌄</span></div><div id="sys" class="submenu open"><a href="/schools">🏫 School Profile - Register Schools</a><a href="/classes">🏫 Classes</a><a href="/profile">👤 My Profile</a></div><div class="user-box"><div class="user-avatar">DO</div><div><div style="font-size:13px;font-weight:600">Davis Ouma</div><div style="font-size:11px;color:#64748b">oumadavis940@gmail.com</div></div></div></div><div class="main"><div class="topbar"><div><b>{school}</b></div><div style="display:flex;gap:12px;align-items:center"><span>🔔</span><div style="display:flex;align-items:center;gap:8px"><div class="user-avatar">DO</div><div style="font-size:12px"><b>Davis Ouma</b><br>Admin</div></div></div></div><div class="content"><h2>{title}</h2><p style="color:#64748b;font-size:13px">DAVISCHOOL Management System</p>{body}</div></div><script>function toggle(id){{let e=document.getElementById(id); if(e) e.classList.toggle('open');}} function editCell(b,t,i,f){{let v=prompt("Enter "+f,b.dataset.val||""); if(v===null)return; fetch("/api/edit/"+t,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{id:i,field:f,value:v}})}}).then(r=>r.json()).then(d=>{{if(d.ok)location.reload()}})}} function saveMark(a,t,y,s){{let v=prompt("Score"); if(v===null)return; fetch("/marks/save",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{adm:a,term:t,year:y,subject:s,score:v}})}}).then(()=>location.reload())}}</script></body></html>"""
@app.get("/login", response_class=HTMLResponse)
def login_page(): return """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>DAVISCHOOL Login</title><style>body{background:#f0f6ff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;font-family:Segoe UI}.box{background:#fff;padding:30px;border-radius:16px;width:360px;box-shadow:0 10px 30px rgba(0,0,0,.08)}input{width:100%;padding:12px;margin:8px 0;border:1px solid #cbd5e1;border-radius:8px}button{width:100%;padding:12px;background:#0f172a;color:#fff;border:none;border-radius:8px;margin-top:10px}</style></head><body><div class="box"><h2 style="text-align:center">DAVISCHOOL</h2><form method="post" action="/login" autocomplete="off"><input name="username" placeholder="Username" autocomplete="off" required><input name="password" type="password" placeholder="Password" autocomplete="new-password" required><button>Login</button></form></div></body></html>"""
@app.post("/login")
def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    con=get_db(); u=con.execute("SELECT * FROM users WHERE username=? AND password=?",(username,password)).fetchone(); con.close()
    if u: request.session["user"]=username; return RedirectResponse("/dashboard", status_code=302)
    return HTMLResponse("<h3>Wrong <a href=/login>Retry</a></h3>")
@app.get("/logout")
def logout(request: Request): request.session.clear(); return RedirectResponse("/login", status_code=302)
@app.get("/")
def root(request: Request): return RedirectResponse("/dashboard" if request.session.get("user") else "/login", status_code=302)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); sc=con.execute("SELECT COUNT(*) FROM students").fetchone()[0]; tc=con.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]; sch=con.execute("SELECT COUNT(*) FROM schools").fetchone()[0]; con.close()
    body=f"""<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px"><div class="card"><h3>Schools Registered</h3><h1>{sch}</h1><a href="/schools">Manage</a></div><div class="card"><h3>Students</h3><h1>{sc}</h1></div><div class="card"><h3>Teachers</h3><h1>{tc}</h1></div></div>"""
    return HTMLResponse(layout("Dashboard", body, request.session.get("user")))
@app.get("/students", response_class=HTMLResponse)
def students_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); studs=con.execute("SELECT * FROM students ORDER BY name").fetchall(); schools=con.execute("SELECT * FROM schools").fetchall(); con.close()
    opts="".join([f"<option>{s['name']}</option>" for s in schools])
    tr="".join([f"<tr><td>{s['adm']}</td><td>{s['name']}</td><td>{s['class']}</td><td>{s['school'] or ''}</td></tr>" for s in studs])
    body=f"""<div class="card"><form method="post" action="/students/add" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px"><input name="adm" placeholder="ADM" required><input name="name" placeholder="Name" required><input name="class" placeholder="Class"><input name="stream" placeholder="Stream"><select name="school"><option>Select School</option>{opts}</select><button class="btn btn-primary">Add Student</button></form></div><div class="card"><table><tr><th>ADM</th><th>Name</th><th>Class</th><th>School</th></tr>{tr}</table></div>"""
    return HTMLResponse(layout("Students List", body, request.session.get("user")))
@app.post("/students/add")
def add_student(adm: str = Form(...), name: str = Form(...), class_: str = Form("", alias="class"), stream: str = Form(""), school: str = Form("")):
    con=get_db()
    try: con.execute("INSERT INTO students (adm,name,class,stream,school) VALUES (?,?,?,?,?)",(adm,name,class_,stream,school)); con.commit()
    except: pass
    con.close(); return RedirectResponse("/students", status_code=302)
@app.get("/teachers", response_class=HTMLResponse)
def teachers_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); ts=con.execute("SELECT * FROM teachers").fetchall(); con.close()
    tr="".join([f"<tr><td>{t['tsc']}</td><td>{t['name']}</td><td>{t['subject']}</td></tr>" for t in ts])
    body=f"""<div class="card"><form method="post" action="/teachers/add" style="display:flex;gap:8px"><input name="tsc" placeholder="TSC"><input name="name" placeholder="Name"><input name="subject" placeholder="Subject"><button class="btn btn-primary">Add</button></form></div><div class="card"><table><tr><th>TSC</th><th>Name</th><th>Subject</th></tr>{tr}</table></div>"""
    return HTMLResponse(layout("Staff List", body, request.session.get("user")))
@app.post("/teachers/add")
def add_teacher(tsc: str = Form(...), name: str = Form(...), subject: str = Form(...)): con=get_db(); con.execute("INSERT OR IGNORE INTO teachers (tsc,name,subject) VALUES (?,?,?)",(tsc,name,subject)); con.commit(); con.close(); return RedirectResponse("/teachers", status_code=302)
@app.get("/marks", response_class=HTMLResponse)
def marks_page(request: Request, class_: str = "", term: str = "Term 1", year: str = "2026", subject: str = "Mathematics"):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); studs=con.execute("SELECT * FROM students").fetchall() if not class_ else con.execute("SELECT * FROM students WHERE class LIKE?",(f"%{class_}%",)).fetchall()
    marks={};
    for m in con.execute("SELECT * FROM marks WHERE term=? AND year=? AND subject=?",(term,year,subject)).fetchall(): marks[m["adm"]]=m
    con.close(); tr="".join([f"<tr><td>{s['adm']}</td><td>{s['name']}</td><td onclick=\"saveMark('{s['adm']}','{term}','{year}','{subject}')\" style='background:#fff9c4;cursor:pointer'>{marks.get(s['adm'],{}).get('score','Enter')}</td></tr>" for s in studs])
    body=f"""<div class="card"><form method="get" style="display:flex;gap:8px"><input name="class_" placeholder="Class"><select name="term"><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name="year" value="{year}"><select name="subject"><option>Mathematics</option><option>English</option></select><button class="btn btn-primary">Load</button></form></div><div class="card"><table><tr><th>ADM</th><th>Name</th><th>Score</th></tr>{tr}</table></div>"""
    return HTMLResponse(layout("Record Marks", body, request.session.get("user")))
@app.post("/marks/save")
async def save_marks(request: Request):
    d=await request.json(); con=get_db(); ex=con.execute("SELECT id FROM marks WHERE adm=? AND term=? AND year=? AND subject=?",(d["adm"],d["term"],d["year"],d["subject"])).fetchone()
    if ex: con.execute("UPDATE marks SET score=? WHERE id=?",(d["score"],ex["id"]))
    else: con.execute("INSERT INTO marks (adm,term,year,subject,score) VALUES (?,?,?,?,?)",(d["adm"],d["term"],d["year"],d["subject"],d["score"]))
    con.commit(); con.close(); return {"ok":True}
@app.get("/fees", response_class=HTMLResponse)
def fees_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); fees=con.execute("SELECT * FROM fees").fetchall(); con.close()
    tr="".join([f"<tr><td>{r['adm']}</td><td>{r['amount']}</td></tr>" for r in fees])
    body=f"""<div class="card"><form method="post" action="/fees/add" style="display:flex;gap:8px"><input name="adm" placeholder="ADM"><input name="amount" type="number" placeholder="Paid"><button class="btn btn-primary">Add</button></form></div><div class="card"><table><tr><th>ADM</th><th>Paid</th></tr>{tr}</table></div>"""
    return HTMLResponse(layout("Fees", body, request.session.get("user")))
@app.post("/fees/add")
def add_fee(adm: str = Form(...), amount: int = Form(...)): con=get_db(); con.execute("INSERT INTO fees (adm,amount,date) VALUES (?,?,?)",(adm,amount,datetime.now().strftime("%Y-%m-%d"))); con.commit(); con.close(); return RedirectResponse("/fees", status_code=302)
@app.get("/classes", response_class=HTMLResponse)
def classes_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); cls=con.execute("SELECT class, COUNT(*) as cnt FROM students GROUP BY class").fetchall(); con.close()
    tr="".join([f"<tr><td>{c['class']}</td><td>{c['cnt']}</td></tr>" for c in cls])
    return HTMLResponse(layout("Class List", f"<div class='card'><table><tr><th>Class</th><th>Count</th></tr>{tr}</table></div>", request.session.get("user")))
@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    return HTMLResponse(layout("Exam Analysis", "<div class='card'>Analysis will show here after marks entry</div>", request.session.get("user")))
@app.get("/schools", response_class=HTMLResponse)
def schools_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); schools=con.execute("SELECT * FROM schools").fetchall(); con.close()
    tr="".join([f"<tr><td>{s['name']}</td><td>{s['code']}</td><td>{s['box']}</td><td>{s['phone']}</td></tr>" for s in schools])
    body=f"""<div class="card"><h3>Register New School (like MABALE etc)</h3><form method="post" action="/schools/add" style="display:grid;grid-template-columns:1fr 1fr;gap:10px"><input name="name" placeholder="School Name e.g. MABALE COMPREHENSIVE" required><input name="code" placeholder="Code e.g. 10069"><input name="box" placeholder="P.O Box 300-50400"><input name="phone" placeholder="Phone 0721307699"><input name="email" placeholder="Email"><button class="btn btn-primary" style="grid-column:span 2">Add School</button></form></div><div class="card"><table><tr><th>School</th><th>Code</th><th>Box</th><th>Phone</th></tr>{tr if tr else '<tr><td colspan=4>No schools yet - Add MABALE above!</td></tr>'}</table></div>"""
    return HTMLResponse(layout("School Profile - Register Schools", body, request.session.get("user")))
@app.post("/schools/add")
def add_school(name: str = Form(...), code: str = Form(""), box: str = Form(""), phone: str = Form(""), email: str = Form("")):
    con=get_db(); con.execute("INSERT INTO schools (name,code,box,phone,email) VALUES (?,?,?,?,?)",(name,code,box,phone,email)); con.commit(); con.close(); return RedirectResponse("/schools", status_code=302)
@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    body="""<div style="display:grid;grid-template-columns:320px 1fr;gap:18px"><div class="card" style="text-align:center"><div style="width:80px;height:80px;background:#0f172a;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto;font-size:24px">DO</div><h3>Davis Ouma</h3><span style="background:#e0f2fe;color:#0369a1;padding:4px 10px;border-radius:20px">School Admin</span><p>oumadavis940@gmail.com</p><p style="font-size:12px">DAVISCHOOL SYSTEM<br>Multi-School Platform</p></div><div class="card"><h3>Personal Information</h3><label>Full Name</label><input value="Davis Ouma"><br><br><label>Email</label><input value="oumadavis940@gmail.com"><br><br><a href="/schools" class="btn btn-primary">Go Register Schools</a></div></div>"""
    return HTMLResponse(layout("My Profile", body, request.session.get("user")))
@app.post("/api/edit/{table}")
async def api_edit(table: str, request: Request):
    d=await request.json(); con=get_db()
    try: con.execute(f"UPDATE {table} SET {d['field']}=? WHERE id=?",(d["value"],d["id"])); con.commit(); con.close(); return {"ok":True}
    except Exception as e: con.close(); return {"ok":False,"error":str(e)}
