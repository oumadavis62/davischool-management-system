import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
DB="school.db"
app=FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davi-secret-2026-zeraki")
def init_db():
    con=sqlite3.connect(DB); c=con.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, adm TEXT UNIQUE, name TEXT, class TEXT, stream TEXT, gender TEXT, kcpe INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, tsc TEXT UNIQUE, name TEXT, subject TEXT, phone TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, adm TEXT, term TEXT, year TEXT, subject TEXT, score INTEGER, grade TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, adm TEXT, amount INTEGER, balance INTEGER, term TEXT, year TEXT, date TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)")
    c.execute("INSERT OR IGNORE INTO users VALUES (1,'admin','Ouma@940','admin')")
    con.commit(); con.close()
init_db()
def get_db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; return con
def layout(t,b,u="admin"):
    return f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>{t}</title><style>*{{box-sizing:border-box;font-family:Segoe UI}}body{{margin:0;background:#f4f6f9;display:flex;min-height:100vh}}.sidebar{{width:250px;background:#0f1e3a;color:#fff;padding:20px 0;position:fixed;height:100vh}}.sidebar a{{display:block;color:#b9c3d6;padding:12px 22px;text-decoration:none}}.sidebar a:hover{{background:#1a345f;color:#fff}}.main{{margin-left:250px;flex:1;padding:20px}}.card{{background:#fff;border-radius:10px;padding:18px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin-bottom:18px}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px 12px;border:1px solid #e5e7eb;text-align:left;font-size:14px}}th{{background:#f1f5f9}}.btn{{padding:8px 14px;border-radius:6px;border:none;cursor:pointer;text-decoration:none;display:inline-block}}.btn-primary{{background:#0f1e3a;color:#fff}}.btn-sm{{padding:5px 10px;font-size:13px}}.btn-danger{{background:#ef4444;color:#fff}}input,select{{padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;width:100%}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}}@media(max-width:800px){{.sidebar{{width:100%;position:relative;height:auto}}.main{{margin-left:0}}}}</style></head><body><div class="sidebar"><h2>DAVISCHOOL</h2><a href="/dashboard">Dashboard</a><a href="/students">Students</a><a href="/teachers">Teachers</a><a href="/marks">Marks Entry</a><a href="/fees">Fees</a><a href="/classes">Classes</a><a href="/reports">Reports</a><a href="/logout" style="color:#ff8a8a;margin-top:30px;display:block;padding:12px 22px">Logout ({u})</a></div><div class="main"><h2>{t}</h2>{b}</div><script>function editCell(btn,type,id,field){{let v=prompt("Enter new "+field,btn.dataset.val||"");if(v===null)return;fetch("/api/edit/"+type,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{id:id,field:field,value:v}})}}).then(r=>r.json()).then(d=>{{if(d.ok)location.reload();else alert(d.error)}})}} function saveMark(adm,term,year,subj){{let v=prompt("Enter score");if(v===null)return;fetch("/marks/save",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{adm:adm,term:term,year:year,subject:subj,score:v}})}}).then(()=>location.reload())}}</script></body></html>"""
@app.get("/login", response_class=HTMLResponse)
def login_page(): return """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{background:#0f1e3a;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;font-family:Segoe UI}.box{background:#fff;padding:30px;border-radius:12px;width:340px}input{width:100%;padding:11px;margin:8px 0;border:1px solid #ccc;border-radius:6px}button{width:100%;padding:12px;background:#0f1e3a;color:#fff;border:none;border-radius:6px;margin-top:10px}</style></head><body><div class="box"><h2 style="text-align:center">DAVI SCHOOL Zeraki</h2><form method="post" action="/login"><input name="username" placeholder="admin" required><input name="password" type="password" placeholder="Ouma@940" required><button>Login</button></form></div></body></html>"""
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
    con=get_db(); sc=con.execute("SELECT COUNT(*) FROM students").fetchone()[0]; tc=con.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]; fc=con.execute("SELECT COALESCE(SUM(amount),0) FROM fees").fetchone()[0]; studs=con.execute("SELECT * FROM students ORDER BY id DESC LIMIT 5").fetchall(); con.close()
    rows="".join([f"<tr><td>{s['adm']}</td><td>{s['name']}</td><td>{s['class']} {s['stream']}</td></tr>" for s in studs])
    body=f"""<div class="grid"><div class="card"><h3>Students</h3><h1>{sc}</h1><a href="/students" class="btn btn-primary btn-sm">View</a></div><div class="card"><h3>Teachers</h3><h1>{tc}</h1><a href="/teachers" class="btn btn-primary btn-sm">View</a></div><div class="card"><h3>Fees</h3><h1>KSh {fc}</h1><a href="/fees" class="btn btn-primary btn-sm">View</a></div><div class="card"><h3>Marks Zeraki Style</h3><p>Click cell to edit</p><a href="/marks" class="btn btn-primary btn-sm">Enter Marks</a></div></div><div class="card"><h3>Recent</h3><table><tr><th>ADM</th><th>Name</th><th>Class</th></tr>{rows}</table></div>"""
    return HTMLResponse(layout("Dashboard - Zeraki Style", body, request.session.get("user")))
@app.get("/students", response_class=HTMLResponse)
def students_page(request: Request, q: str = ""):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db()
    if q:
        studs=con.execute("SELECT * FROM students WHERE name LIKE? OR adm LIKE?", (f"%{q}%",f"%{q}%")).fetchall()
    else:
        studs=con.execute("SELECT * FROM students ORDER BY class,name").fetchall()
    con.close()
    tr=""
    for s in studs: tr+=f"<tr><td><span data-val='{s['adm']}' onclick=\"editCell(this,'students',{s['id']},'adm')\" style='cursor:pointer;border-bottom:1px dashed #999'>{s['adm']} edit</span></td><td><span data-val='{s['name']}' onclick=\"editCell(this,'students',{s['id']},'name')\" style='cursor:pointer'>{s['name']} edit</span></td><td>{s['class']} {s['stream']}</td><td><a href='/students/delete/{s['id']}' class='btn btn-danger btn-sm'>Del</a></td></tr>"
    body=f"""<div class="card"><form method="post" action="/students/add" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px"><input name="adm" placeholder="ADM" required><input name="name" placeholder="Name" required><input name="class" placeholder="Form" required><input name="stream" placeholder="Stream" required><select name="gender"><option>Male</option><option>Female</option></select><input name="kcpe" placeholder="KCPE"><button class="btn btn-primary">Add</button></form></div><div class="card"><form method="get"><input name="q" value="{q}" placeholder="Search" style="max-width:250px"><button class="btn btn-primary btn-sm">Search</button></form><table style="margin-top:10px"><tr><th>ADM Click edit</th><th>Name Click edit</th><th>Class</th><th>Action</th></tr>{tr}</table></div>"""
    return HTMLResponse(layout("Students", body, request.session.get("user")))
@app.post("/students/add")
def add_student(request: Request, adm: str = Form(...), name: str = Form(...), class_: str = Form(..., alias="class"), stream: str = Form(...), gender: str = Form(...), kcpe: str = Form("")):
    con=get_db()
    try: con.execute("INSERT INTO students (adm,name,class,stream,gender,kcpe) VALUES (?,?,?,?,?,?)",(adm,name,class_,stream,gender,kcpe)); con.commit()
    except: pass
    con.close(); return RedirectResponse("/students", status_code=302)
@app.get("/students/delete/{sid}")
def del_student(sid: int): con=get_db(); con.execute("DELETE FROM students WHERE id=?",(sid,)); con.commit(); con.close(); return RedirectResponse("/students", status_code=302)
@app.get("/teachers", response_class=HTMLResponse)
def teachers_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); ts=con.execute("SELECT * FROM teachers ORDER BY name").fetchall(); con.close()
    tr="".join([f"<tr><td>{t['tsc']}</td><td><span data-val='{t['name']}' onclick=\"editCell(this,'teachers',{t['id']},'name')\" style='cursor:pointer'>{t['name']} edit</span></td><td>{t['subject']}</td><td><a href='/teachers/delete/{t['id']}' class='btn btn-danger btn-sm'>Del</a></td></tr>" for t in ts])
    body=f"""<div class="card"><form method="post" action="/teachers/add" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px"><input name="tsc" placeholder="TSC" required><input name="name" placeholder="Name" required><input name="subject" placeholder="Subject" required><input name="phone" placeholder="Phone"><button class="btn btn-primary">Add Teacher</button></form></div><div class="card"><table><tr><th>TSC</th><th>Name edit</th><th>Subject</th><th>Action</th></tr>{tr}</table></div>"""
    return HTMLResponse(layout("Teachers", body, request.session.get("user")))
@app.post("/teachers/add")
def add_teacher(tsc: str = Form(...), name: str = Form(...), subject: str = Form(...), phone: str = Form("")): con=get_db(); con.execute("INSERT OR IGNORE INTO teachers (tsc,name,subject,phone) VALUES (?,?,?,?)",(tsc,name,subject,phone)); con.commit(); con.close(); return RedirectResponse("/teachers", status_code=302)
@app.get("/teachers/delete/{tid}")
def del_teacher(tid: int): con=get_db(); con.execute("DELETE FROM teachers WHERE id=?",(tid,)); con.commit(); con.close(); return RedirectResponse("/teachers", status_code=302)
@app.get("/marks", response_class=HTMLResponse)
def marks_page(request: Request, class_: str = "", term: str = "Term 1", year: str = "2026", subject: str = "Mathematics"):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db()
    if class_:
        studs=con.execute("SELECT * FROM students WHERE class LIKE? ORDER BY name",(f"%{class_}%",)).fetchall()
    else:
        studs=con.execute("SELECT * FROM students ORDER BY class,name").fetchall()
    marks={}
    for m in con.execute("SELECT * FROM marks WHERE term=? AND year=? AND subject=?",(term,year,subject)).fetchall(): marks[m["adm"]]=m
    con.close(); tr=""
    for s in studs:
        mm=marks.get(s["adm"]); sc=mm["score"] if mm else ""; gr=mm["grade"] if mm else ""
        tr+=f"<tr><td>{s['adm']}</td><td>{s['name']}</td><td>{s['class']} {s['stream']}</td><td onclick=\"saveMark('{s['adm']}','{term}','{year}','{subject}')\" style='cursor:pointer;background:#fff9c4;padding:6px'>{sc if sc!='' else 'Enter'}</td><td>{gr}</td></tr>"
    body=f"""<div class="card"><form method="get" style="display:flex;gap:8px;flex-wrap:wrap"><input name="class_" value="{class_}" placeholder="Class" style="max-width:100px"><select name="term" style="max-width:110px"><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name="year" value="{year}" style="max-width:80px"><select name="subject" style="max-width:140px"><option>Mathematics</option><option>English</option><option>Kiswahili</option><option>Chemistry</option><option>Biology</option><option>Physics</option></select><button class="btn btn-primary btn-sm">Load</button></form><p>Click yellow cell to edit - Zeraki style</p></div><div class="card"><table><tr><th>ADM</th><th>Name</th><th>Class</th><th>Score {subject} (Click)</th><th>Grade</th></tr>{tr}</table></div>"""
    return HTMLResponse(layout(f"Marks - {subject} {term}", body, request.session.get("user")))
@app.post("/marks/save")
async def save_marks(request: Request):
    d=await request.json(); adm=d.get("adm"); term=d.get("term"); year=d.get("year"); subj=d.get("subject"); score=int(d.get("score") or 0)
    def g(s): return "A" if s>=80 else "B" if s>=60 else "C" if s>=45 else "D" if s>=30 else "E"
    grade=g(score); con=get_db(); ex=con.execute("SELECT id FROM marks WHERE adm=? AND term=? AND year=? AND subject=?",(adm,term,year,subj)).fetchone()
    if ex: con.execute("UPDATE marks SET score=?,grade=? WHERE id=?",(score,grade,ex["id"]))
    else: con.execute("INSERT INTO marks (adm,term,year,subject,score,grade) VALUES (?,?,?,?,?,?)",(adm,term,year,subj,score,grade))
    con.commit(); con.close(); return {"ok":True}
@app.get("/fees", response_class=HTMLResponse)
def fees_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); fees=con.execute("SELECT f.*, s.name FROM fees f LEFT JOIN students s ON f.adm=s.adm ORDER BY f.id DESC LIMIT 100").fetchall(); con.close()
    tr="".join([f"<tr><td>{r['adm']}</td><td>{r['name'] or ''}</td><td>{r['amount']}</td><td>{r['balance']}</td><td>{r['term']} {r['year']}</td></tr>" for r in fees])
    body=f"""<div class="card"><form method="post" action="/fees/add" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px"><input name="adm" placeholder="ADM" required><input name="amount" type="number" placeholder="Paid" required><input name="balance" type="number" placeholder="Balance"><select name="term"><option>Term 1</option><option>Term 2</option><option>Term 3</option></select><input name="year" value="2026"><button class="btn btn-primary">Add</button></form></div><div class="card"><table><tr><th>ADM</th><th>Name</th><th>Paid</th><th>Bal</th><th>Term</th></tr>{tr}</table></div>"""
    return HTMLResponse(layout("Fees", body, request.session.get("user")))
@app.post("/fees/add")
def add_fee(adm: str = Form(...), amount: int = Form(...), balance: int = Form(0), term: str = Form(...), year: str = Form(...)): con=get_db(); con.execute("INSERT INTO fees (adm,amount,balance,term,year,date) VALUES (?,?,?,?,?,?)",(adm,amount,balance,term,year,datetime.now().strftime("%Y-%m-%d"))); con.commit(); con.close(); return RedirectResponse("/fees", status_code=302)
@app.get("/classes", response_class=HTMLResponse)
def classes_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); cls=con.execute("SELECT class, stream, COUNT(*) as cnt FROM students GROUP BY class, stream").fetchall(); con.close()
    tr="".join([f"<tr><td>Form {c['class']}</td><td>{c['stream']}</td><td>{c['cnt']}</td></tr>" for c in cls])
    body=f"<div class='card'><table><tr><th>Class</th><th>Stream</th><th>Count</th></tr>{tr if tr else '<tr><td colspan=3>No data</td></tr>'}</table></div>"
    return HTMLResponse(layout("Classes", body, request.session.get("user")))
@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db(); av=con.execute("SELECT subject, AVG(score) as av FROM marks GROUP BY subject").fetchall(); con.close(); tr="".join([f"<tr><td>{a['subject']}</td><td>{round(a['av'],1)}</td></tr>" for a in av])
    body=f"<div class='card'><table><tr><th>Subject</th><th>Mean</th></tr>{tr}</table></div>"
    return HTMLResponse(layout("Reports", body, request.session.get("user")))
@app.post("/api/edit/{table}")
async def api_edit(table: str, request: Request):
    d=await request.json(); id=d.get("id"); field=d.get("field"); val=d.get("value")
    allowed={"students":["adm","name","class","stream","gender","kcpe"],"teachers":["tsc","name","subject","phone"]}
    if table not in allowed or field not in allowed[table]: return {"ok":False,"error":"not allowed"}
    con=get_db()
    try: con.execute(f"UPDATE {table} SET {field}=? WHERE id=?",(val,id)); con.commit(); con.close(); return {"ok":True}
    except Exception as e: con.close(); return {"ok":False,"error":str(e)}
