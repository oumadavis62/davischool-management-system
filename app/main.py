import os
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import sqlite3
from datetime import datetime

DB = "school.db"
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="davi-secret-2026-zeraki")

def init_db():
    con = sqlite3.connect(DB)
    c = con.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, admission_no TEXT UNIQUE, name TEXT, class_name TEXT, stream TEXT, gender TEXT, parent_phone TEXT, status TEXT DEFAULT 'Active')")
    c.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, name TEXT, tsc_no TEXT, subject TEXT, phone TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, name TEXT, stream TEXT, class_teacher TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, name TEXT, code TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, name TEXT, term TEXT, year TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, student_id INTEGER, subject TEXT, exam_id INTEGER, score INTEGER, grade TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, student_id INTEGER, amount INTEGER, paid INTEGER, balance INTEGER, term TEXT)")
    c.execute("SELECT COUNT(*) FROM subjects")
    if c.fetchone()[0]==0:
        for s in [("Mathematics","MATH"),("English","ENG"),("Kiswahili","KIS"),("Chemistry","CHEM"),("Biology","BIO"),("Physics","PHY"),("History","HIST"),("Geography","GEO"),("CRE","CRE"),("Business","BST"),("Agriculture","AGRI")]:
            c.execute("INSERT INTO subjects (name,code) VALUES (?,?)", s)
    c.execute("SELECT COUNT(*) FROM exams")
    if c.fetchone()[0]==0:
        c.execute("INSERT INTO exams (name,term,year) VALUES ('Opener','Term 1','2026')")
        c.execute("INSERT INTO exams (name,term,year) VALUES ('Mid Term','Term 1','2026')")
        c.execute("INSERT INTO exams (name,term,year) VALUES ('End Term','Term 1','2026')")
    con.commit()
    con.close()

init_db()

def get_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def calc_grade(score):
    if score>=80: return "A"
    if score>=70: return "A-"
    if score>=60: return "B+"
    if score>=50: return "B"
    if score>=40: return "C+"
    if score>=30: return "C"
    if score>=20: return "D"
    return "E"

ADMIN_USER = "admin"
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "Ouma@940")

BASE_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<title>Davi School - Zeraki Style</title>
<style>
.sidebar{background:#0f172a; min-height:100vh; color:white}
.sidebar a{color:#cbd5e1; text-decoration:none; display:block; padding:12px 20px; border-radius:8px; margin:4px 10px}
.sidebar a:hover,.sidebar a.active{background:#1e293b; color:white}
.card-stat{border-left:4px solid #3b82f6}
.editable{border:1px dashed transparent; padding:4px}
.editable:focus{border:1px dashed #3b82f6; background:#f0f9ff; outline:none}
.btn-zeraki{background:#2563eb; color:white}
</style>
</head>
<body>
<div class="container-fluid">
<div class="row">
<div class="col-md-2 sidebar p-0 py-3">
<h5 class="px-4 mb-4"><i class="bi bi-mortarboard"></i> DAVI SCHOOL</h5>
<a href="/dashboard"><i class="bi bi-speedometer2"></i> Dashboard</a>
<a href="/students"><i class="bi bi-people"></i> Students</a>
<a href="/marks"><i class="bi bi-pencil-square"></i> Marks Entry</a>
<a href="/exams"><i class="bi bi-file-earmark-text"></i> Exams</a>
<a href="/classes"><i class="bi bi-door-open"></i> Classes</a>
<a href="/teachers"><i class="bi bi-person-workspace"></i> Teachers</a>
<a href="/fees"><i class="bi bi-cash-stack"></i> Fees</a>
<a href="/subjects"><i class="bi bi-book"></i> Subjects</a>
<a href="/logout" class="mt-5 text-danger"><i class="bi bi-box-arrow-right"></i> Logout</a>
</div>
<div class="col-md-10 p-4 bg-light">
{{content}}
</div>
</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
async function saveField(table,id,field,value){
  let res= await fetch('/api/edit/'+table+'/'+id, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({field:field,value:value})});
  if(res.ok){ document.getElementById('save-'+id).innerHTML='<span class=text-success>Saved</span>'; setTimeout(()=>document.getElementById('save-'+id).innerHTML='',1500) }
}
async function saveMark(id, subject){
  let score = document.getElementById('score-'+id+'-'+subject).innerText;
  let res= await fetch('/api/save-mark', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({student_id:id, subject:subject, score:parseInt(score)})});
  if(res.ok) location.reload();
}
</script>
</body>
</html>
"""

def render_page(active, content):
    from jinja2 import Template
    t = Template(BASE_HTML)
    return t.render(active=active, content=content)

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <div class="container mt-5"><div class="row justify-content-center"><div class="col-md-4">
    <div class="card shadow"><div class="card-body p-4">
    <h4 class="text-center mb-3">DAVI SCHOOL LOGIN</h4>
    <p class="text-center text-muted small">Zeraki Style System</p>
    <form method="post" action="/login">
    <input class="form-control mb-3" name="username" placeholder="Username" value="admin" required>
    <input class="form-control mb-3" type="password" name="password" placeholder="Password" required>
    <button class="btn btn-primary w-100">Login</button>
    </form></div></div></div></div></div>
    """

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username==ADMIN_USER and password==ADMIN_PASS:
        request.session["user"]=username
        return RedirectResponse("/dashboard", status_code=302)
    return HTMLResponse("<h3>Wrong password. Use Ouma@940</h3><a href='/login'>Back</a>")

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")

@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/dashboard")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)
    con=get_db()
    students=con.execute("SELECT COUNT(*) as c FROM students").fetchone()["c"]
    teachers=con.execute("SELECT COUNT(*) as c FROM teachers").fetchone()["c"]
    fees_bal=con.execute("SELECT SUM(balance) as s FROM fees").fetchone()["s"] or 0
    top=con.execute("SELECT s.name, s.class_name, AVG(m.score) as avg FROM marks m JOIN students s ON m.student_id=s.id GROUP BY s.id ORDER BY avg DESC LIMIT 5").fetchall()
    con.close()
    content=f"""
    <h4>Dashboard - Term 1, 2026</h4>
    <div class="row mt-4">
    <div class="col-md-3"><div class="card card-stat shadow-sm p-3"><small>Students</small><h3>{students}</h3><a href="/students" class="btn btn-sm btn-primary">Manage <i class="bi bi-pencil"></i></a></div></div>
    <div class="col-md-3"><div class="card card-stat shadow-sm p-3" style="border-color:#10b981"><small>Teachers</small><h3>{teachers}</h3><a href="/teachers" class="btn btn-sm btn-success">Manage <i class="bi bi-pencil"></i></a></div></div>
    <div class="col-md-3"><div class="card card-stat shadow-sm p-3" style="border-color:#f59e0b"><small>Fees Balance</small><h3>Ksh {fees_bal}</h3><a href="/fees" class="btn btn-sm btn-warning">Manage <i class="bi bi-pencil"></i></a></div></div>
    <div class="col-md-3"><div class="card card-stat shadow-sm p-3" style="border-color:#8b5cf6"><small>Mean Score</small><h3>6.2 C+</h3><a href="/marks" class="btn btn-sm" style="background:#8b5cf6;color:white">Enter Marks <i class="bi bi-pencil"></i></a></div></div>
    </div>
    <div class="row mt-4">
    <div class="col-md-8"><div class="card shadow-sm p-3"><h6>Top Students</h6><table class="table table-sm"><tr><th>Name</th><th>Class</th><th>Mean</th><th>Action</th></tr>
    {''.join([f"<tr><td>{r['name']}</td><td>{r['class_name']}</td><td>{round(r['avg'],1) if r['avg'] else 0}</td><td><a href='/marks' class='btn btn-sm btn-outline-primary'><i class='bi bi-pencil'></i> Edit Marks</a></td></tr>" for r in top])}
    </table></div></div>
    <div class="col-md-4"><div class="card shadow-sm p-3"><h6>Quick Actions</h6>
    <a href="/students" class="btn btn-outline-primary w-100 mb-2"><i class="bi bi-plus"></i> Add Student</a>
    <a href="/marks" class="btn btn-outline-success w-100 mb-2"><i class="bi bi-pencil-square"></i> Bulk Marks Entry</a>
    <a href="/exams" class="btn btn-outline-dark w-100 mb-2"><i class="bi bi-plus"></i> New Exam</a>
    <a href="/fees" class="btn btn-outline-warning w-100"><i class="bi bi-cash"></i> Record Fees</a>
    </div></div>
    </div>
    """
    return HTMLResponse(render_page("dashboard", content))
@app.get("/students", response_class=HTMLResponse)
def students_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login", status_code=302)
    con=get_db()
    rows=con.execute("SELECT * FROM students ORDER BY id DESC").fetchall()
    con.close()
    table_rows=""
    for r in rows:
        table_rows+=f"""
        <tr>
        <td contenteditable="true" class="editable" onblur="saveField('students',{r['id']},'admission_no',this.innerText)">{r['admission_no']}</td>
        <td contenteditable="true" class="editable" onblur="saveField('students',{r['id']},'name',this.innerText)">{r['name']}</td>
        <td contenteditable="true" class="editable" onblur="saveField('students',{r['id']},'class_name',this.innerText)">{r['class_name']}</td>
        <td>{r['stream']}</td>
        <td contenteditable="true" class="editable" onblur="saveField('students',{r['id']},'parent_phone',this.innerText)">{r['parent_phone']}</td>
        <td><span id="save-{r['id']}"></span>
        <a href="/students/edit/{r['id']}" class="btn btn-sm btn-primary"><i class="bi bi-pencil"></i></a>
        <a href="/students/delete/{r['id']}" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')"><i class="bi bi-trash"></i></a>
        </td></tr>
        """
    content=f"""
    <div class="d-flex justify-content-between"><h4>Students - Editable</h4><button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addStudent"><i class="bi bi-plus"></i> Add Student</button></div>
    <div class="card shadow-sm mt-3 p-3"><small class="text-muted">Tip: Click any cell to edit directly - like Zeraki.</small>
    <table class="table table-hover mt-2"><thead><tr><th>Adm No</th><th>Name</th><th>Class</th><th>Stream</th><th>Parent Phone</th><th>Actions</th></tr></thead><tbody>{table_rows}</tbody></table></div>
    <div class="modal fade" id="addStudent"><div class="modal-dialog"><div class="modal-content"><div class="modal-header"><h6>Add Student</h6></div>
    <form method="post" action="/students/add"><div class="modal-body">
    <input class="form-control mb-2" name="admission_no" placeholder="Admission No" required>
    <input class="form-control mb-2" name="name" placeholder="Full Name" required>
    <input class="form-control mb-2" name="class_name" placeholder="Form 1" required>
    <input class="form-control mb-2" name="stream" placeholder="East/West">
    <input class="form-control mb-2" name="parent_phone" placeholder="Parent Phone">
    <select class="form-control mb-2" name="gender"><option>Male</option><option>Female</option></select>
    </div><div class="modal-footer"><button class="btn btn-primary w-100">Save Student</button></div></form></div></div></div>
    """
    return HTMLResponse(render_page("students", content))

@app.post("/students/add")
def add_student(request: Request, admission_no: str=Form(...), name: str=Form(...), class_name: str=Form(...), stream: str=Form(...), parent_phone: str=Form(...), gender: str=Form(...)):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db()
    try:
        con.execute("INSERT INTO students (admission_no,name,class_name,stream,parent_phone,gender) VALUES (?,?,?,?,?,?)",(admission_no,name,class_name,stream,parent_phone,gender))
        con.commit()
    except: pass
    con.close()
    return RedirectResponse("/students", status_code=302)

@app.get("/students/delete/{id}")
def del_student(request: Request, id: int):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db(); con.execute("DELETE FROM students WHERE id=?",(id,)); con.commit(); con.close()
    return RedirectResponse("/students", status_code=302)

@app.get("/students/edit/{id}", response_class=HTMLResponse)
def edit_student_page(request: Request, id: int):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db(); r=con.execute("SELECT * FROM students WHERE id=?",(id,)).fetchone(); con.close()
    content=f"""
    <h4>Edit Student</h4><div class="card p-4 col-md-6">
    <form method="post" action="/students/update/{id}">
    <input class="form-control mb-2" name="name" value="{r['name']}">
    <input class="form-control mb-2" name="class_name" value="{r['class_name']}">
    <input class="form-control mb-2" name="stream" value="{r['stream']}">
    <input class="form-control mb-2" name="parent_phone" value="{r['parent_phone']}">
    <button class="btn btn-primary">Update</button> <a href="/students" class="btn btn-secondary">Cancel</a>
    </form></div>
    """
    return HTMLResponse(render_page("students", content))

@app.post("/students/update/{id}")
def update_student(request: Request, id: int, name: str=Form(...), class_name: str=Form(...), stream: str=Form(...), parent_phone: str=Form(...)):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db(); con.execute("UPDATE students SET name=?,class_name=?,stream=?,parent_phone=? WHERE id=?",(name,class_name,stream,parent_phone,id)); con.commit(); con.close()
    return RedirectResponse("/students", status_code=302)

@app.get("/marks", response_class=HTMLResponse)
def marks_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db()
    students=con.execute("SELECT * FROM students").fetchall()
    subjects=con.execute("SELECT * FROM subjects").fetchall()
    exams=con.execute("SELECT * FROM exams").fetchall()
    exam_id=exams[0]["id"] if exams else 1
    marks_map={}
    for m in con.execute("SELECT * FROM marks WHERE exam_id=?",(exam_id,)).fetchall():
        marks_map[(m["student_id"],m["subject"])]=m["score"]
    con.close()
    subj_header="".join([f"<th>{s['code']}</th>" for s in subjects])
    rows_html=""
    for st in students:
        cells=""
        for sub in subjects:
            score=marks_map.get((st["id"], sub["code"]), "")
            cells+=f"<td contenteditable='true' class='editable' id='score-{st['id']}-{sub['code']}' onblur=\"saveMark({st['id']},'{sub['code']}')\">{score}</td>"
        rows_html+=f"<tr><td>{st['admission_no']}</td><td>{st['name']}</td><td>{st['class_name']}</td>{cells}<td><a href='/marks/student/{st['id']}' class='btn btn-sm btn-primary'><i class='bi bi-pencil'></i></a></td></tr>"
    content=f"""
    <div class="d-flex justify-content-between"><h4>Marks Entry - Zeraki Style (Click to Edit)</h4></div>
    <div class="card shadow-sm mt-3 p-2" style="overflow:auto"><small>Click score to edit, blur to auto-save.</small>
    <table class="table table-bordered table-sm mt-2"><thead><tr><th>Adm</th><th>Name</th><th>Class</th>{subj_header}<th>Action</th></tr></thead><tbody>{rows_html}</tbody></table></div>
    """
    return HTMLResponse(render_page("marks", content))

@app.post("/api/save-mark")
async def api_save_mark(request: Request):
    if not request.session.get("user"): return {"error":"login"}
    data=await request.json()
    student_id=data["student_id"]; subject=data["subject"]; score=data["score"]
    con=get_db()
    ex=con.execute("SELECT id FROM exams LIMIT 1").fetchone()
    exam_id=ex["id"] if ex else 1
    existing=con.execute("SELECT id FROM marks WHERE student_id=? AND subject=? AND exam_id=?",(student_id,subject,exam_id)).fetchone()
    if existing:
        con.execute("UPDATE marks SET score=?, grade=? WHERE id=?",(score, calc_grade(score), existing["id"]))
    else:
        con.execute("INSERT INTO marks (student_id,subject,exam_id,score,grade) VALUES (?,?,?,?,?)",(student_id,subject,exam_id,score,calc_grade(score)))
    con.commit(); con.close()
    return {"ok":True}

@app.post("/api/edit/{table}/{id}")
async def api_edit(table: str, id: int, request: Request):
    if not request.session.get("user"): return {"error":"login"}
    data=await request.json()
    field=data["field"]; value=data["value"]
    allowed={"students":["admission_no","name","class_name","stream","parent_phone","gender"], "teachers":["name","subject","phone"], "classes":["name","stream","class_teacher"], "subjects":["name","code"], "exams":["name","term","year"], "fees":["amount","paid","balance"]}
    if table not in allowed or field not in allowed[table]: return {"error":"not allowed"}
    con=get_db(); con.execute(f"UPDATE {table} SET {field}=? WHERE id=?",(value,id)); con.commit(); con.close()
    return {"ok":True}
@app.get("/teachers", response_class=HTMLResponse)
def teachers_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db(); rows=con.execute("SELECT * FROM teachers").fetchall(); con.close()
    tr="".join([f"<tr><td contenteditable='true' class='editable' onblur=\"saveField('teachers',{r['id']},'name',this.innerText)\">{r['name']}</td><td contenteditable='true' class='editable' onblur=\"saveField('teachers',{r['id']},'subject',this.innerText)\">{r['subject']}</td><td contenteditable='true' class='editable' onblur=\"saveField('teachers',{r['id']},'phone',this.innerText)\">{r['phone']}</td><td><a href='/teachers/delete/{r['id']}' class='btn btn-sm btn-danger'>Delete</a> <span id='save-{r['id']}'></span></td></tr>" for r in rows])
    content=f"""
    <div class="d-flex justify-content-between"><h4>Teachers - Editable</h4><button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addTeacher">Add Teacher</button></div>
    <div class="card p-3 mt-3"><table class="table"><thead><tr><th>Name</th><th>Subject</th><th>Phone</th><th>Actions</th></tr></thead><tbody>{tr}</tbody></table></div>
    <div class="modal fade" id="addTeacher"><div class="modal-dialog"><div class="modal-content"><form method="post" action="/teachers/add"><div class="modal-body">
    <input class="form-control mb-2" name="name" placeholder="Teacher Name" required><input class="form-control mb-2" name="subject" placeholder="Subject"><input class="form-control mb-2" name="phone" placeholder="Phone"></div>
    <div class="modal-footer"><button class="btn btn-primary w-100">Save</button></div></form></div></div></div>
    """
    return HTMLResponse(render_page("teachers", content))

@app.post("/teachers/add")
def add_teacher(request: Request, name: str=Form(...), subject: str=Form(...), phone: str=Form(...)):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db(); con.execute("INSERT INTO teachers (name,subject,phone) VALUES (?,?,?)",(name,subject,phone)); con.commit(); con.close()
    return RedirectResponse("/teachers", status_code=302)

@app.get("/teachers/delete/{id}")
def del_teacher(request: Request, id: int):
    con=get_db(); con.execute("DELETE FROM teachers WHERE id=?",(id,)); con.commit(); con.close()
    return RedirectResponse("/teachers", status_code=302)

@app.get("/fees", response_class=HTMLResponse)
def fees_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db(); rows=con.execute("SELECT f.*, s.name, s.admission_no FROM fees f JOIN students s ON f.student_id=s.id").fetchall(); students=con.execute("SELECT * FROM students").fetchall(); con.close()
    tr="".join([f"<tr><td>{r['admission_no']}</td><td>{r['name']}</td><td contenteditable='true' class='editable' onblur=\"saveField('fees',{r['id']},'amount',this.innerText)\">{r['amount']}</td><td contenteditable='true' class='editable' onblur=\"saveField('fees',{r['id']},'paid',this.innerText)\">{r['paid']}</td><td>{r['balance']}</td><td><a href='/fees/delete/{r['id']}' class='btn btn-sm btn-danger'>Del</a></td></tr>" for r in rows])
    opts="".join([f"<option value='{s['id']}'>{s['admission_no']} - {s['name']}</option>" for s in students])
    content=f"""
    <div class="d-flex justify-content-between"><h4>Fees - Editable</h4><button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addFee">Record Fee</button></div>
    <div class="card p-3 mt-3"><table class="table"><thead><tr><th>Adm</th><th>Name</th><th>Amount</th><th>Paid</th><th>Balance</th><th>Actions</th></tr></thead><tbody>{tr}</tbody></table></div>
    <div class="modal fade" id="addFee"><div class="modal-dialog"><div class="modal-content"><form method="post" action="/fees/add"><div class="modal-body">
    <select class="form-control mb-2" name="student_id">{opts}</select><input class="form-control mb-2" name="amount" placeholder="Total Amount" type="number"><input class="form-control mb-2" name="paid" placeholder="Paid" type="number"><input class="form-control mb-2" name="term" placeholder="Term 1"></div>
    <div class="modal-footer"><button class="btn btn-primary w-100">Save</button></div></form></div></div></div>
    """
    return HTMLResponse(render_page("fees", content))

@app.post("/fees/add")
def add_fee(request: Request, student_id: int=Form(...), amount: int=Form(...), paid: int=Form(...), term: str=Form(...)):
    bal=amount-paid
    con=get_db(); con.execute("INSERT INTO fees (student_id,amount,paid,balance,term) VALUES (?,?,?,?,?)",(student_id,amount,paid,bal,term)); con.commit(); con.close()
    return RedirectResponse("/fees", status_code=302)

@app.get("/fees/delete/{id}")
def del_fee(request: Request, id: int):
    con=get_db(); con.execute("DELETE FROM fees WHERE id=?",(id,)); con.commit(); con.close()
    return RedirectResponse("/fees", status_code=302)

@app.get("/classes", response_class=HTMLResponse)
def classes_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db(); rows=con.execute("SELECT * FROM classes").fetchall(); con.close()
    tr="".join([f"<tr><td contenteditable='true' class='editable' onblur=\"saveField('classes',{r['id']},'name',this.innerText)\">{r['name']}</td><td contenteditable='true' class='editable' onblur=\"saveField('classes',{r['id']},'stream',this.innerText)\">{r['stream']}</td><td contenteditable='true' class='editable' onblur=\"saveField('classes',{r['id']},'class_teacher',this.innerText)\">{r['class_teacher']}</td><td><a href='/classes/delete/{r['id']}' class='btn btn-sm btn-danger'>Del</a> <span id='save-{r['id']}'></span></td></tr>" for r in rows])
    content=f"""
    <div class="d-flex justify-content-between"><h4>Classes - Editable</h4><button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addClass">Add Class</button></div>
    <div class="card p-3 mt-3"><table class="table"><thead><tr><th>Class</th><th>Stream</th><th>Class Teacher</th><th>Actions</th></tr></thead><tbody>{tr}</tbody></table></div>
    <div class="modal fade" id="addClass"><div class="modal-dialog"><div class="modal-content"><form method="post" action="/classes/add"><div class="modal-body">
    <input class="form-control mb-2" name="name" placeholder="Form 1"><input class="form-control mb-2" name="stream" placeholder="East"><input class="form-control mb-2" name="class_teacher" placeholder="Class Teacher"></div>
    <div class="modal-footer"><button class="btn btn-primary w-100">Save</button></div></form></div></div></div>
    """
    return HTMLResponse(render_page("classes", content))

@app.post("/classes/add")
def add_class(request: Request, name: str=Form(...), stream: str=Form(...), class_teacher: str=Form(...)):
    con=get_db(); con.execute("INSERT INTO classes (name,stream,class_teacher) VALUES (?,?,?)",(name,stream,class_teacher)); con.commit(); con.close()
    return RedirectResponse("/classes", status_code=302)

@app.get("/classes/delete/{id}")
def del_class(request: Request, id: int):
    con=get_db(); con.execute("DELETE FROM classes WHERE id=?",(id,)); con.commit(); con.close()
    return RedirectResponse("/classes", status_code=302)

@app.get("/subjects", response_class=HTMLResponse)
def subjects_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db(); rows=con.execute("SELECT * FROM subjects").fetchall(); con.close()
    tr="".join([f"<tr><td contenteditable='true' class='editable' onblur=\"saveField('subjects',{r['id']},'name',this.innerText)\">{r['name']}</td><td contenteditable='true' class='editable' onblur=\"saveField('subjects',{r['id']},'code',this.innerText)\">{r['code']}</td><td><a href='/subjects/delete/{r['id']}' class='btn btn-sm btn-danger'>Del</a> <span id='save-{r['id']}'></span></td></tr>" for r in rows])
    content=f"""
    <div class="d-flex justify-content-between"><h4>Subjects - Editable</h4><button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addSub">Add Subject</button></div>
    <div class="card p-3 mt-3"><table class="table"><thead><tr><th>Name</th><th>Code</th><th>Actions</th></tr></thead><tbody>{tr}</tbody></table></div>
    <div class="modal fade" id="addSub"><div class="modal-dialog"><div class="modal-content"><form method="post" action="/subjects/add"><div class="modal-body">
    <input class="form-control mb-2" name="name" placeholder="Mathematics"><input class="form-control mb-2" name="code" placeholder="MATH"></div>
    <div class="modal-footer"><button class="btn btn-primary w-100">Save</button></div></form></div></div></div>
    """
    return HTMLResponse(render_page("subjects", content))

@app.post("/subjects/add")
def add_sub(request: Request, name: str=Form(...), code: str=Form(...)):
    con=get_db(); con.execute("INSERT INTO subjects (name,code) VALUES (?,?)",(name,code)); con.commit(); con.close()
    return RedirectResponse("/subjects", status_code=302)

@app.get("/subjects/delete/{id}")
def del_sub(request: Request, id: int):
    con=get_db(); con.execute("DELETE FROM subjects WHERE id=?",(id,)); con.commit(); con.close()
    return RedirectResponse("/subjects", status_code=302)

@app.get("/exams", response_class=HTMLResponse)
def exams_page(request: Request):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db(); rows=con.execute("SELECT * FROM exams").fetchall(); con.close()
    tr="".join([f"<tr><td contenteditable='true' class='editable' onblur=\"saveField('exams',{r['id']},'name',this.innerText)\">{r['name']}</td><td contenteditable='true' class='editable' onblur=\"saveField('exams',{r['id']},'term',this.innerText)\">{r['term']}</td><td contenteditable='true' class='editable' onblur=\"saveField('exams',{r['id']},'year',this.innerText)\">{r['year']}</td><td><a href='/exams/delete/{r['id']}' class='btn btn-sm btn-danger'>Del</a> <a href='/marks' class='btn btn-sm btn-primary'>Marks</a> <span id='save-{r['id']}'></span></td></tr>" for r in rows])
    content=f"""
    <div class="d-flex justify-content-between"><h4>Exams - Editable</h4><button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addExam">Add Exam</button></div>
    <div class="card p-3 mt-3"><table class="table"><thead><tr><th>Exam</th><th>Term</th><th>Year</th><th>Actions</th></tr></thead><tbody>{tr}</tbody></table></div>
    <div class="modal fade" id="addExam"><div class="modal-dialog"><div class="modal-content"><form method="post" action="/exams/add"><div class="modal-body">
    <input class="form-control mb-2" name="name" placeholder="End Term"><input class="form-control mb-2" name="term" placeholder="Term 1"><input class="form-control mb-2" name="year" placeholder="2026"></div>
    <div class="modal-footer"><button class="btn btn-primary w-100">Save</button></div></form></div></div></div>
    """
    return HTMLResponse(render_page("exams", content))

@app.post("/exams/add")
def add_exam(request: Request, name: str=Form(...), term: str=Form(...), year: str=Form(...)):
    con=get_db(); con.execute("INSERT INTO exams (name,term,year) VALUES (?,?,?)",(name,term,year)); con.commit(); con.close()
    return RedirectResponse("/exams", status_code=302)

@app.get("/exams/delete/{id}")
def del_exam(request: Request, id: int):
    con=get_db(); con.execute("DELETE FROM exams WHERE id=?",(id,)); con.commit(); con.close()
    return RedirectResponse("/exams", status_code=302)

@app.get("/marks/student/{id}", response_class=HTMLResponse)
def marks_student(request: Request, id: int):
    if not request.session.get("user"): return RedirectResponse("/login")
    con=get_db()
    st=con.execute("SELECT * FROM students WHERE id=?",(id,)).fetchone()
    subjects=con.execute("SELECT * FROM subjects").fetchall()
    marks=con.execute("SELECT * FROM marks WHERE student_id=?",(id,)).fetchall()
    m_map={m["subject"]:m["score"] for m in marks}
    con.close()
    rows="".join([f"<tr><td>{s['name']}</td><td contenteditable='true' class='editable' id='score-{id}-{s['code']}'>{m_map.get(s['code'],'')}</td><td><button onclick=\"saveMark({id},'{s['code']}')\" class='btn btn-sm btn-success'>Save</button></td></tr>" for s in subjects])
    content=f"""<h4>Edit Marks for {st['name']}</h4><div class="card p-3 mt-3"><table class="table"><tr><th>Subject</th><th>Score</th><th>Save</th></tr>{rows}</table><a href="/marks" class="btn btn-secondary">Back</a></div>"""
    return HTMLResponse(render_page("marks", content))
