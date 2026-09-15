import sqlite3, os, hashlib, secrets, csv, io
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from itsdangerous import URLSafeTimedSerializer
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY","davischool-secret-2026"))
serializer = URLSafeTimedSerializer(os.getenv("SECRET_KEY","davischool-secret-2026"))
DB = "davischool.db"

def get_db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn=get_db(); c=conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, code TEXT UNIQUE, password_hash TEXT, role TEXT DEFAULT 'school')")
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, username TEXT UNIQUE, password_hash TEXT, role TEXT, department TEXT, plain_temp TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, stream TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm_no TEXT, name TEXT, class_id INTEGER, gender TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, teacher TEXT, department TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, school_id INTEGER, student_id INTEGER, subject_id INTEGER, exam_id INTEGER, score INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS timetable (id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER, day TEXT, period INTEGER, subject_id INTEGER, teacher TEXT)")
    c.execute("SELECT * FROM schools WHERE code='ADMIN001'")
    if not c.fetchone():
        ph=hashlib.sha256("Admin@2026".encode()).hexdigest()
        c.execute("INSERT INTO schools (name,code,password_hash,role) VALUES (?,?,?,?)", ("Admin","ADMIN001",ph,"admin"))
    conn.commit(); conn.close()

init_db()
def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()
def check_pw(p,h): return hash_pw(p)==h
def get_user(request: Request):
    token=request.cookies.get("session")
    if not token: return None
    try: return serializer.loads(token, max_age=86400)
    except: return None

DAYS=["Monday","Tuesday","Wednesday","Thursday","Friday"]
PERIODS=[1,2,3,4,5,6,7,8]

def layout(title, body, user=None, beautiful=False):
    nav=""
    if user:
        role=user.get('role','')
        if role=='admin':
            nav='<a href="/dashboard">Dashboard</a> | <a href="/schools">Schools</a> | <a href="/logout">Logout</a>'
        else:
            base='<a href="/dashboard">Dashboard</a> | '
            if role in ['principal','school','deputy','dos','hod','admin']:
                base+='<a href="/students">Students</a> | <a href="/classes">Classes</a> | <a href="/subjects">Subjects</a> | <a href="/exams">Exams</a> | <a href="/marks">Marks</a> | <a href="/timetable">Timetable ASC</a> | <a href="/reports">Reports</a> | '
            elif role=='teacher':
                base+='<a href="/students">My Students</a> | <a href="/marks">Enter Marks</a> | <a href="/timetable">My Timetable</a> | '
            elif role=='bursar':
                base+='<a href="/students">Students</a> | '
            if role in ['principal','school','admin','deputy']:
                base+='<a href="/staff">Staff/Roles</a> | '
            nav=base+'<a href="/logout">Logout ('+role+')</a>'
    style="body{font-family:'Segoe UI',Arial;margin:0;background:#eef2f7}.top{background:linear-gradient(90deg,#1a237e,#3949ab);color:white;padding:14px 22px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 2px 8px rgba(0,0,0,.2)}.top a{color:white;text-decoration:none;margin-right:14px;font-weight:500}.container{padding:22px}.card{background:white;padding:18px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.08);margin-bottom:18px;border:1px solid #e8eaf6} table{width:100%;border-collapse:collapse} th,td{border:1px solid #d0d7e3;padding:8px;font-size:14px} th{background:#e8eaf6}.btn{background:#3949ab;color:white;padding:7px 14px;border:none;border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block}.btn-green{background:#2e7d32}.btn-red{background:#c62828}.wall td{height:56px;min-width:115px}.slot{background:#e3f2fd;border-radius:6px;padding:4px;font-size:12px}.conflict{background:#ffcdd2;border:1px solid #e53935}.login-bg{background:linear-gradient(135deg,#1a237e,#5c6bc0);min-height:100vh;display:flex;align-items:center;justify-content:center}.login-card{background:white;width:420px;padding:32px;border-radius:16px;box-shadow:0 12px 32px rgba(0,0,0,.25);text-align:center}.login-card h2{color:#1a237e;margin-bottom:6px}.login-card p{color:#666;font-size:13px;margin-bottom:18px} @media print{.top,.no-print{display:none}}"
    html="<html><head><title>"+title+"</title><style>"+style+"</style></head>"
    if beautiful:
        html+="<body>"+body+"</body></html>"
        return html
    html+="<body><div class='top'><div><b>DaviSchool Manager</b></div><div>"+nav+"</div></div><div class='container'><h2>"+title+"</h2>"+body+"</div></body></html>"
    return html

@app.get("/", response_class=HTMLResponse)
def home(): return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
def login_page():
    body="<div class='login-bg'><div class='login-card'><div style='font-size:42px'>🏫</div><h2>DaviSchool Manager</h2><p>Beautiful School Management • Zeraki Style • ASC Timetable</p><form method='post' action='/login' style='text-align:left'><label style='font-weight:600;font-size:13px'>School Code / Username / Email</label><br><input name='code' placeholder='e.g ADMIN001 or oumadavis62@gmail.com or otieno.4821' required style='width:100%;padding:12px;border:1px solid #c5cae9;border-radius:8px;margin:6px 0 14px 0'><br><label style='font-weight:600;font-size:13px'>Password</label><br><input type='password' name='password' required placeholder='Enter password' style='width:100%;padding:12px;border:1px solid #c5cae9;border-radius:8px;margin:6px 0 18px 0'><br><button class='btn' type='submit' style='width:100%;padding:12px;font-size:15px;border-radius:8px'>Login →</button></form><p style='margin-top:16px;font-size:12px;color:#888'>Admin: ADMIN001 / Admin@2026</p></div></div>"
    return HTMLResponse(layout("Login - DaviSchool", body, None, beautiful=True))

@app.post("/login")
def do_login(request: Request, code: str = Form(...), password: str = Form(...)):
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM schools WHERE code=?", (code,))
    sch=c.fetchone()
    if sch and check_pw(password, sch["password_hash"]):
        data={"school_id":sch["id"],"role":sch["role"],"name":sch["name"],"code":sch["code"],"username":sch["code"]}
        token=serializer.dumps(data)
        conn.close()
        resp=RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("session", token, httponly=True)
        return resp
    c.execute("SELECT * FROM users WHERE username=?", (code,))
    u=c.fetchone()
    if u and check_pw(password, u["password_hash"]):
        data={"school_id":u["school_id"],"role":u["role"],"name":u["name"],"code":u["username"],"username":u["username"],"user_id":u["id"]}
        token=serializer.dumps(data)
        conn.close()
        resp=RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("session", token, httponly=True)
        return resp
    c.execute("SELECT * FROM schools WHERE code=? OR name=?", (code,code))
    sch2=c.fetchone()
    if sch2 and check_pw(password, sch2["password_hash"]):
        data={"school_id":sch2["id"],"role":sch2["role"],"name":sch2["name"],"code":sch2["code"],"username":sch2["code"]}
        token=serializer.dumps(data)
        conn.close()
        resp=RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("session", token, httponly=True)
        return resp
    conn.close()
    body="<div class='login-bg'><div class='login-card'><h2 style='color:#c62828'>Invalid Login</h2><p>Code or password incorrect.</p><a class='btn' href='/login'>Back to Login</a></div></div>"
    return HTMLResponse(layout("Login Failed", body, None, beautiful=True))

@app.get("/logout")
def logout():
    r=RedirectResponse("/login"); r.delete_cookie("session"); return r

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    role=user['role']
    if role=='admin':
        c.execute("SELECT COUNT(*) as cnt FROM schools WHERE role!='admin'"); sc=c.fetchone()["cnt"]
        body="<div class='card'><h3>System Admin</h3>Schools: "+str(sc)+"</div><div class='card'><a class='btn' href='/schools'>Manage Schools</a></div>"
    else:
        sid=user['school_id']
        c.execute("SELECT COUNT(*) as cnt FROM students WHERE school_id=?", (sid,)); stu=c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM classes WHERE school_id=?", (sid,)); cls=c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM users WHERE school_id=?", (sid,)); staff=c.fetchone()["cnt"]
        body="<div class='card' style='background:linear-gradient(90deg,#e8eaf6,#fff)'><b>Welcome "+user['name']+"</b> <span style='background:#3949ab;color:white;padding:3px 8px;border-radius:12px;font-size:11px'>"+role.upper()+"</span><br><br>Students: "+str(stu)+" | Classes: "+str(cls)+" | Staff: "+str(staff)+"</div>"
        if role in ['principal','school','deputy','dos']:
            body+="<div class='card'><a class='btn' href='/students'>Students</a> <a class='btn' href='/classes'>Classes</a> <a class='btn' href='/subjects'>Subjects</a> <a class='btn' href='/exams'>Exams</a> <a class='btn' href='/marks'>Marks & Ranking</a> <a class='btn' href='/timetable' style='background:#00897b'>Timetable ASC</a> <a class='btn' href='/reports' style='background:#ef6c00'>Reports & Merit</a> <a class='btn' href='/staff'>Staff & Roles</a></div>"
        elif role=='teacher':
            body+="<div class='card'><p>Teacher limited access: Enter marks and view students/timetable.</p><a class='btn' href='/students'>My Students</a> <a class='btn' href='/marks'>Enter Marks</a> <a class='btn' href='/timetable'>My Timetable</a></div>"
        elif role=='hod':
            body+="<div class='card'><a class='btn' href='/subjects'>My Department</a> <a class='btn' href='/marks'>Approve Marks</a> <a class='btn' href='/reports'>Reports</a></div>"
        else:
            body+="<div class='card'><a class='btn' href='/students'>Students</a> <a class='btn' href='/classes'>Classes</a> <a class='btn' href='/subjects'>Subjects</a> <a class='btn' href='/marks'>Marks</a> <a class='btn' href='/timetable'>Timetable</a> <a class='btn' href='/reports'>Reports</a> <a class='btn' href='/staff'>Staff</a></div>"
    conn.close()
    return HTMLResponse(layout("Dashboard", body, user))

@app.get("/staff", response_class=HTMLResponse)
def staff_page(request: Request):
    user=get_user(request)
    if not user or user['role'] not in ['principal','school','admin','deputy']: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM users WHERE school_id=?", (user['school_id'],)); rows=c.fetchall()
    tr=""
    for r in rows:
        tr+="<tr><td>"+r['name']+"</td><td>"+r['username']+"</td><td>"+r['role']+"</td><td>"+(r['department'] or "")+"</td><td>"+(r['plain_temp'] or "hidden")+"</td><td><a href='/staff/delete/"+str(r['id'])+"' class='btn btn-red'>Delete</a></td></tr>"
    body="<div class='card'><h3>Add Staff + Auto Username/Password (Zeraki)</h3><form method='post' action='/staff/add'><input name='name' placeholder='Full Name e.g Otieno' required><select name='role' required><option value='teacher'>Teacher</option><option value='hod'>HOD</option><option value='dos'>Director of Studies</option><option value='deputy'>Deputy Principal</option><option value='bursar'>Bursar</option></select><input name='department' placeholder='Department'><button class='btn'>Create + Auto Login</button></form><small>Auto username like otieno.4821 and password Tch@2941 shown once.</small></div><div class='card'><table><tr><th>Name</th><th>Username</th><th>Role</th><th>Dept</th><th>Temp Password</th><th>Action</th></tr>"+tr+"</table></div>"
    conn.close()
    return HTMLResponse(layout("Staff & Roles", body, user))

@app.post("/staff/add")
def staff_add(request: Request, name: str=Form(...), role: str=Form(...), department: str=Form(...)):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    uname=name.lower().split()[0]+"."+str(secrets.randbelow(9000)+1000)
    pwd="Tch@"+str(secrets.randbelow(9000)+1000)
    conn=get_db(); c=conn.cursor()
    try:
        c.execute("INSERT INTO users (school_id,name,username,password_hash,role,department,plain_temp) VALUES (?,?,?,?,?,?,?)", (user['school_id'],name,uname,hash_pw(pwd),role,department,pwd))
        conn.commit()
    except: pass
    conn.close()
    return RedirectResponse("/staff", status_code=302)

@app.get("/staff/delete/{uid}")
def staff_del(request: Request, uid: int):
    user=get_user(request)
    if not user or user['role'] not in ['principal','school','admin','deputy']: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("DELETE FROM users WHERE id=? AND school_id=?", (uid,user['school_id'])); conn.commit(); conn.close()
    return RedirectResponse("/staff", status_code=302)

@app.get("/classes", response_class=HTMLResponse)
def classes_page(request: Request):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM classes WHERE school_id=?", (user['school_id'],)); rows=c.fetchall()
    tr="".join(["<tr><td>"+r['name']+" "+(r['stream'] or "")+"</td></tr>" for r in rows])
    form="<div class='card'><form method='post' action='/classes/add'><input name='name' placeholder='Class e.g Form 2' required><input name='stream' placeholder='Stream'><button class='btn'>Add Class</button></form></div>" if user['role'] in ['principal','school','admin','deputy','dos'] else ""
    body=form+"<div class='card'><table><tr><th>Class</th></tr>"+tr+"</table></div>"
    conn.close()
    return HTMLResponse(layout("Classes", body, user))

@app.post("/classes/add")
def classes_add(request: Request, name: str=Form(...), stream: str=Form(...)):
    user=get_user(request)
    conn=get_db(); c=conn.cursor()
    c.execute("INSERT INTO classes (school_id,name,stream) VALUES (?,?,?)", (user['school_id'],name,stream)); conn.commit(); conn.close()
    return RedirectResponse("/classes", status_code=302)

@app.get("/students", response_class=HTMLResponse)
def students_page(request: Request):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=?", (user['school_id'],)); rows=c.fetchall()
    tr="".join(["<tr><td>"+r['adm_no']+"</td><td>"+r['name']+"</td><td>"+(r['cname'] or "")+"</td></tr>" for r in rows])
    c.execute("SELECT * FROM classes WHERE school_id=?", (user['school_id'],)); cls=c.fetchall()
    opts="".join(["<option value='"+str(cl['id'])+"'>"+cl['name']+" "+(cl['stream'] or "")+"</option>" for cl in cls])
    form=""
    if user['role'] in ['principal','school','admin','deputy','dos']:
        form="<div class='card'><form method='post' action='/students/add'><input name='adm_no' placeholder='Adm No' required><input name='name' placeholder='Name' required><select name='class_id'>"+opts+"</select><button class='btn'>Add Student</button></form> <a class='btn' href='/download/students/csv' style='background:#2e7d32'>Download Excel (CSV)</a></div>"
    body=form+"<div class='card'><table><tr><th>Adm</th><th>Name</th><th>Class</th></tr>"+tr+"</table></div>"
    conn.close()
    return HTMLResponse(layout("Students", body, user))

@app.post("/students/add")
def students_add(request: Request, adm_no: str=Form(...), name: str=Form(...), class_id: int=Form(...)):
    user=get_user(request)
    conn=get_db(); c=conn.cursor()
    c.execute("INSERT INTO students (school_id,adm_no,name,class_id) VALUES (?,?,?,?)", (user['school_id'],adm_no,name,class_id)); conn.commit(); conn.close()
    return RedirectResponse("/students", status_code=302)

@app.get("/subjects", response_class=HTMLResponse)
def subjects_page(request: Request):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor(); c.execute("SELECT * FROM subjects WHERE school_id=?", (user['school_id'],)); rows=c.fetchall()
    tr="".join(["<tr><td>"+r['name']+"</td><td>"+(r['teacher'] or "")+"</td><td>"+(r['department'] or "")+"</td></tr>" for r in rows])
    form="<div class='card'><form method='post' action='/subjects/add'><input name='name' placeholder='Subject' required><input name='teacher' placeholder='Teacher'><input name='department' placeholder='Dept'><button class='btn'>Add</button></form></div>" if user['role'] in ['principal','school','admin','deputy','dos','hod'] else ""
    body=form+"<div class='card'><table><tr><th>Subject</th><th>Teacher</th><th>Dept</th></tr>"+tr+"</table></div>"
    conn.close()
    return HTMLResponse(layout("Subjects", body, user))

@app.post("/subjects/add")
def subjects_add(request: Request, name: str=Form(...), teacher: str=Form(...), department: str=Form(...)):
    user=get_user(request)
    conn=get_db(); c=conn.cursor()
    c.execute("INSERT INTO subjects (school_id,name,teacher,department) VALUES (?,?,?,?)", (user['school_id'],name,teacher,department)); conn.commit(); conn.close()
    return RedirectResponse("/subjects", status_code=302)

@app.get("/exams", response_class=HTMLResponse)
def exams_page(request: Request):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor(); c.execute("SELECT * FROM exams WHERE school_id=?", (user['school_id'],)); rows=c.fetchall()
    tr="".join(["<tr><td>"+r['name']+"</td><td>"+(r['term'] or "")+"</td><td>"+str(r['year'] or "")+"</td><td><a class='btn' href='/reports/merit?exam_id="+str(r['id'])+"'>Merit</a></td></tr>" for r in rows])
    form="<div class='card'><form method='post' action='/exams/add'><input name='name' placeholder='Exam' required><input name='term' placeholder='Term'><input name='year' placeholder='2026'><button class='btn'>Add Exam</button></form></div>" if user['role'] in ['principal','school','admin','deputy','dos'] else ""
    body=form+"<div class='card'><table><tr><th>Exam</th><th>Term</th><th>Year</th><th>Action</th></tr>"+tr+"</table></div>"
    conn.close()
    return HTMLResponse(layout("Exams", body, user))

@app.post("/exams/add")
def exams_add(request: Request, name: str=Form(...), term: str=Form(...), year: int=Form(...)):
    user=get_user(request)
    conn=get_db(); c=conn.cursor()
    c.execute("INSERT INTO exams (school_id,name,term,year) VALUES (?,?,?,?)", (user['school_id'],name,term,year)); conn.commit(); conn.close()
    return RedirectResponse("/exams", status_code=302)

@app.get("/marks", response_class=HTMLResponse)
def marks_page(request: Request, exam_id: int=0, subject_id: int=0):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM exams WHERE school_id=?", (user['school_id'],)); exams=c.fetchall()
    c.execute("SELECT * FROM subjects WHERE school_id=?", (user['school_id'],)); subs=c.fetchall()
    c.execute("SELECT s.*, cl.name as cname FROM students s LEFT JOIN classes cl ON s.class_id=cl.id WHERE s.school_id=?", (user['school_id'],)); studs=c.fetchall()
    if not exams:
        conn.close()
        return HTMLResponse(layout("Marks", "<div class='card'>Add Exams first</div>", user))
    if exam_id==0: exam_id=exams[0]['id']
    if subject_id==0 and subs: subject_id=subs[0]['id']
    c.execute("SELECT * FROM marks WHERE school_id=? AND exam_id=? AND subject_id=?", (user['school_id'],exam_id,subject_id)); existing={}
    for m in c.fetchall(): existing[m['student_id']]=m['score']
    exam_opts="".join(["<option value='"+str(e['id'])+"' "+("selected" if e['id']==exam_id else "")+">"+e['name']+"</option>" for e in exams])
    sub_opts="".join(["<option value='"+str(s['id'])+"' "+("selected" if s['id']==subject_id else "")+">"+s['name']+"</option>" for s in subs])
    rows=""
    for st in studs:
        val=existing.get(st['id'],"")
        rows+="<tr><td>"+st['adm_no']+"</td><td>"+st['name']+"</td><td>"+(st['cname'] or "")+"</td><td><input name='score_"+str(st['id'])+"' value='"+str(val)+"' style='width:60px'></td></tr>"
    body="<div class='card no-print'><form method='get' action='/marks'><select name='exam_id'>"+exam_opts+"</select><select name='subject_id'>"+sub_opts+"</select><button class='btn'>Load</button> <a class='btn' href='/download/marks/csv?exam_id="+str(exam_id)+"&subject_id="+str(subject_id)+"' style='background:#2e7d32'>Download Excel</a></form></div>"
    body+="<div class='card'><form method='post' action='/marks/save'><input type='hidden' name='exam_id' value='"+str(exam_id)+"'><input type='hidden' name='subject_id' value='"+str(subject_id)+"'><table><tr><th>Adm</th><th>Name</th><th>Class</th><th>Score</th></tr>"+rows+"</table><br><button class='btn'>Save Marks</button></form></div>"
    conn.close()
    return HTMLResponse(layout("Marks Entry", body, user))

@app.post("/marks/save")
async def marks_save(request: Request, exam_id: int=Form(...), subject_id: int=Form(...)):
    user=get_user(request)
    form=await request.form()
    conn=get_db(); c=conn.cursor()
    for k,v in form.items():
        if k.startswith("score_"):
            try:
                sid=int(k.split("_")[1])
                if v!='':
                    score=int(v)
                    c.execute("SELECT id FROM marks WHERE school_id=? AND student_id=? AND exam_id=? AND subject_id=?", (user['school_id'],sid,exam_id,subject_id))
                    ex=c.fetchone()
                    if ex: c.execute("UPDATE marks SET score=? WHERE id=?", (score,ex['id']))
                    else: c.execute("INSERT INTO marks (school_id,student_id,exam_id,subject_id,score) VALUES (?,?,?,?,?)", (user['school_id'],sid,exam_id,subject_id,score))
            except: pass
    conn.commit(); conn.close()
    return RedirectResponse("/marks?exam_id="+str(exam_id)+"&subject_id="+str(subject_id), status_code=302)

@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM exams WHERE school_id=?", (user['school_id'],)); exams=c.fetchall()
    c.execute("SELECT * FROM classes WHERE school_id=?", (user['school_id'],)); classes=c.fetchall()
    exam_opts="".join(["<option value='"+str(e['id'])+"'>"+e['name']+" "+(e['term'] or "")+"</option>" for e in exams])
    class_opts="".join(["<option value='"+str(cl['id'])+"'>"+cl['name']+" "+(cl['stream'] or "")+"</option>" for cl in classes])
    body="<div class='card'><h3>Report Cards & Merit Lists</h3></div><div class='card'><h4>Report Cards</h4><form method='get' action='/reports/card'><select name='exam_id'>"+exam_opts+"</select><select name='class_id'>"+class_opts+"</select><button class='btn'>Generate</button></form></div><div class='card'><h4>Merit List</h4><form method='get' action='/reports/merit'><select name='exam_id'>"+exam_opts+"</select><select name='class_id'>"+class_opts+"</select><button class='btn' style='background:#ef6c00'>Generate Merit</button></form></div>"
    conn.close()
    return HTMLResponse(layout("Reports", body, user))

@app.get("/reports/card", response_class=HTMLResponse)
def report_card(request: Request, exam_id: int=0, class_id: int=0):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM students WHERE school_id=? AND class_id=?", (user['school_id'],class_id)); students=c.fetchall()
    c.execute("SELECT * FROM subjects WHERE school_id=?", (user['school_id'],)); subjects=c.fetchall()
    c.execute("SELECT * FROM marks WHERE school_id=? AND exam_id=?", (user['school_id'],exam_id))
    marks={}
    for m in c.fetchall(): marks[(m['student_id'],m['subject_id'])]=m['score']
    cards=""
    for st in students:
        total=0; rows=""
        for sub in subjects:
            sc=marks.get((st['id'],sub['id']),0)
            total+=sc
            grade="E"
            if sc>=80: grade="A"
            elif sc>=60: grade="B"
            elif sc>=40: grade="C"
            elif sc>=20: grade="D"
            rows+="<tr><td>"+sub['name']+"</td><td>"+str(sc)+"</td><td>"+grade+"</td></tr>"
        mean=round(total/len(subjects),1) if subjects else 0
        cards+="<div class='card' style='page-break-after:always'><h3 style='text-align:center'>"+user['name']+"<br>Report Card</h3><p><b>Name:</b> "+st['name']+" | <b>Adm:</b> "+st['adm_no']+"</p><table><tr><th>Subject</th><th>Score</th><th>Grade</th></tr>"+rows+"<tr><th>Total: "+str(total)+"</th><th>Mean: "+str(mean)+"</th><th></th></tr></table><p>Principal: __________</p><button class='btn no-print' onclick='window.print()'>Print / Save as PDF</button></div>"
    body=cards if cards else "<div class='card'>No students</div>"
    conn.close()
    return HTMLResponse(layout("Report Cards", body, user))

@app.get("/reports/merit", response_class=HTMLResponse)
def merit_list(request: Request, exam_id: int=0, class_id: int=0):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    q="SELECT * FROM students WHERE school_id=?"; params=[user['school_id']]
    if class_id!=0: q+=" AND class_id=?"; params.append(class_id)
    c.execute(q, params); students=c.fetchall()
    c.execute("SELECT * FROM marks WHERE school_id=? AND exam_id=?", (user['school_id'],exam_id)); all_marks=c.fetchall()
    c.execute("SELECT COUNT(*) as cnt FROM subjects WHERE school_id=?", (user['school_id'],)); sub_cnt=c.fetchone()["cnt"] or 1
    data=[]
    for st in students:
        total=sum([m['score'] for m in all_marks if m['student_id']==st['id']])
        mean=round(total/sub_cnt,1)
        data.append((st,total,mean))
    data.sort(key=lambda x: x[1], reverse=True)
    tr=""; pos=1
    for st,total,mean in data:
        tr+="<tr><td>"+str(pos)+"</td><td>"+st['adm_no']+"</td><td>"+st['name']+"</td><td>"+str(total)+"</td><td>"+str(mean)+"</td></tr>"
        pos+=1
    body="<div class='card no-print'><a class='btn' href='/download/merit/csv?exam_id="+str(exam_id)+"&class_id="+str(class_id)+"' style='background:#2e7d32'>Download Excel (CSV)</a> <button class='btn' onclick='window.print()'>Print / PDF</button></div><div class='card'><h3>Merit List</h3><table><tr><th>Pos</th><th>Adm</th><th>Name</th><th>Total</th><th>Mean</th></tr>"+tr+"</table></div>"
    conn.close()
    return HTMLResponse(layout("Merit List", body, user))

@app.get("/download/{dtype}/csv")
def download_csv(request: Request, dtype: str, exam_id: int=0, subject_id: int=0, class_id: int=0):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    output=io.StringIO(); writer=csv.writer(output)
    if dtype=="students":
        c.execute("SELECT * FROM students WHERE school_id=?", (user['school_id'],)); rows=c.fetchall()
        writer.writerow(["Adm No","Name","Class ID"])
        for r in rows: writer.writerow([r['adm_no'],r['name'],r['class_id']])
    elif dtype=="marks":
        c.execute("SELECT s.adm_no,s.name, m.score FROM marks m JOIN students s ON m.student_id=s.id WHERE m.school_id=? AND m.exam_id=? AND m.subject_id=?", (user['school_id'],exam_id,subject_id)); rows=c.fetchall()
        writer.writerow(["Adm","Name","Score"])
        for r in rows: writer.writerow([r['adm_no'],r['name'],r['score']])
    elif dtype=="merit":
        c.execute("SELECT * FROM students WHERE school_id=?"+(" AND class_id=? " if class_id!=0 else ""), (user['school_id'],class_id) if class_id!=0 else (user['school_id'],))
        students=c.fetchall()
        c.execute("SELECT * FROM marks WHERE school_id=? AND exam_id=?", (user['school_id'],exam_id)); all_marks=c.fetchall()
        c.execute("SELECT COUNT(*) as cnt FROM subjects WHERE school_id=?", (user['school_id'],)); sub_cnt=c.fetchone()["cnt"] or 1
        writer.writerow(["Pos","Adm","Name","Total","Mean"])
        data=[]
        for st in students:
            total=sum([m['score'] for m in all_marks if m['student_id']==st['id']])
            mean=round(total/sub_cnt,1)
            data.append((st,total,mean))
        data.sort(key=lambda x: x[1], reverse=True)
        pos=1
        for st,total,mean in data:
            writer.writerow([pos,st['adm_no'],st['name'],total,mean]); pos+=1
    conn.close()
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={dtype}_report.csv"})

@app.get("/timetable", response_class=HTMLResponse)
def timetable_page(request: Request, class_id: int = 0, view: str = "class"):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    sid=user['school_id']
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM classes WHERE school_id=?", (sid,)); classes=c.fetchall()
    if not classes:
        conn.close()
        return HTMLResponse(layout("Timetable ASC", '<div class="card">Add Classes first</div>', user))
    if class_id==0: class_id=classes[0]['id']
    c.execute("SELECT * FROM subjects WHERE school_id=?", (sid,)); subjects=c.fetchall()
    sub_map={}
    for s in subjects: sub_map[s['id']]=s
    c.execute("SELECT day, period, teacher, COUNT(*) as cnt FROM timetable WHERE school_id=? GROUP BY day, period, teacher HAVING cnt>1", (sid,)); conflicts=c.fetchall()
    conflict_set=set()
    for cf in conflicts: conflict_set.add((cf['day'], cf['period'], cf['teacher']))
    c.execute("SELECT * FROM timetable WHERE school_id=? AND class_id=?", (sid, class_id)); tts=c.fetchall()
    tt_map={}
    for t in tts: tt_map[(t['day'], t['period'])]=t
    c.execute("SELECT * FROM timetable WHERE school_id=?", (sid,)); all_tt=c.fetchall()
    class_opts=""
    for cl in classes:
        sel="selected" if cl['id']==class_id else ""
        class_opts+="<option value='"+str(cl['id'])+"' "+sel+">"+cl['name']+" "+(cl['stream'] or "")+"</option>"
    sub_opts=""
    for s in subjects:
        sub_opts+="<option value='"+str(s['id'])+"'>"+s['name']+" ("+(s['teacher'] or "")+")</option>"
    grid="<table class='wall'><tr><th>Period</th>"
    for d in DAYS: grid+="<th>"+d+"</th>"
    grid+="</tr>"
    for p in PERIODS:
        grid+="<tr><th>P"+str(p)+"</th>"
        for d in DAYS:
            key=(d,p)
            if key in tt_map:
                rec=tt_map[key]
                sub=sub_map.get(rec['subject_id'])
                sname=sub['name'] if sub else "?"
                teacher=rec['teacher']
                is_conf=(d,p,teacher) in conflict_set
                cls_name="slot conflict" if is_conf else "slot"
                grid+="<td><div class='"+cls_name+"'><b>"+sname+"</b><br><small>"+teacher+"</small><br><a href='/timetable/delete/"+str(rec['id'])+"?class_id="+str(class_id)+"' class='no-print' style='color:red;font-size:10px'>x</a></div></td>"
            else:
                grid+="<td></td>"
        grid+="</tr>"
    grid+="</table>"
    teacher_html=""
    if view=="teacher":
        teacher_html="<table><tr><th>Teacher</th>"
        for d in DAYS: teacher_html+="<th>"+d+"</th>"
        teacher_html+="</tr>"
        teachers=list(set([r['teacher'] for r in all_tt if r['teacher']]))
        for tch in teachers:
            teacher_html+="<tr><td><b>"+tch+"</b></td>"
            for d in DAYS:
                cells=[]
                for r in all_tt:
                    if r['teacher']==tch and r['day']==d:
                        cl_name=next((cl['name']+" "+(cl['stream'] or "") for cl in classes if cl['id']==r['class_id']), "?")
                        sub=sub_map.get(r['subject_id'])
                        sname=sub['name'] if sub else "?"
                        cells.append(sname+"@"+cl_name+" P"+str(r['period']))
                teacher_html+="<td><small>"+"<br>".join(cells)+"</small></td>"
            teacher_html+="</tr>"
        teacher_html+="</table>"
    view_sel_class="selected" if view=="class" else ""
    view_sel_teacher="selected" if view=="teacher" else ""
    body="<div class='card no-print'><form method='get' action='/timetable' style='display:flex;gap:8px;flex-wrap:wrap'><select name='class_id'>"+class_opts+"</select><select name='view'><option value='class' "+view_sel_class+">Class WallMaster (ASC)</option><option value='teacher' "+view_sel_teacher+">Teacher View</option></select><button class='btn'>View</button><button class='btn' type='button' onclick='window.print()' style='background:#2e7d32'>Print Poster / PDF</button></form></div>"
    body+="<div class='card no-print'><h4>Add Slot (ASC)</h4><form method='post' action='/timetable/add'><input type='hidden' name='class_id' value='"+str(class_id)+"'><select name='day' required>"
    for d in DAYS: body+="<option>"+d+"</option>"
    body+="</select><select name='period' required>"
    for p in PERIODS: body+="<option value='"+str(p)+"'>Period "+str(p)+"</option>"
    body+="</select><select name='subject_id' required>"+sub_opts+"</select><input name='teacher' placeholder='Teacher Name' required><button class='btn'>Add Slot</button></form></div>"
    body+="<div class='card'><h3>ASC Timetable - Class ID "+str(class_id)+"</h3>"
    if view=="class": body+=grid
    else: body+=teacher_html
    body+="</div><div class='card no-print'><h4>Conflicts: "+str(len(conflicts))+"</h4><ul>"
    if conflicts:
        for cf in conflicts: body+="<li style='color:red'>"+cf['teacher']+" double booked "+cf['day']+" P"+str(cf['period'])+"</li>"
    else: body+="<li>No conflicts</li>"
    body+="</ul></div>"
    conn.close()
    return HTMLResponse(layout("Timetable ASC Format", body, user))

@app.post("/timetable/add")
def timetable_add(request: Request, class_id: int=Form(...), day: str=Form(...), period: int=Form(...), subject_id: int=Form(...), teacher: str=Form(...)):
    user=get_user(request)
    conn=get_db(); c=conn.cursor()
    c.execute("INSERT INTO timetable (school_id,class_id,day,period,subject_id,teacher) VALUES (?,?,?,?,?,?)", (user['school_id'],class_id,day,period,subject_id,teacher))
    conn.commit(); conn.close()
    return RedirectResponse("/timetable?class_id="+str(class_id), status_code=302)

@app.get("/timetable/delete/{tid}")
def timetable_del(request: Request, tid: int, class_id: int=0):
    user=get_user(request)
    conn=get_db(); c=conn.cursor()
    c.execute("DELETE FROM timetable WHERE id=? AND school_id=?", (tid, user['school_id']))
    conn.commit(); conn.close()
    return RedirectResponse("/timetable?class_id="+str(class_id), status_code=302)

@app.get("/schools", response_class=HTMLResponse)
def schools_page(request: Request):
    user=get_user(request)
    if not user or user['role']!='admin': return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor(); c.execute("SELECT * FROM schools WHERE role!='admin'"); rows=c.fetchall()
    tr=""
    for r in rows: tr+="<tr><td>"+r['name']+"</td><td>"+r['code']+"</td><td><a href='/schools/delete/"+str(r['id'])+"' class='btn btn-red'>Del</a></td></tr>"
    body="<div class='card'><form method='post' action='/schools/add'><input name='name' placeholder='School Name' required><input name='code' placeholder='Code' required><input name='password' placeholder='Password' required><button class='btn'>Add</button></form></div><div class='card'><table><tr><th>Name</th><th>Code</th><th>Act</th></tr>"+tr+"</table></div>"
    conn.close()
    return HTMLResponse(layout("Schools", body, user))

@app.post("/schools/add")
def schools_add(request: Request, name: str=Form(...), code: str=Form(...), password: str=Form(...)):
    conn=get_db(); c=conn.cursor()
    try:
        c.execute("INSERT INTO schools (name,code,password_hash,role) VALUES (?,?,?,?)", (name,code,hash_pw(password),"school")); conn.commit()
    except: pass
    conn.close()
    return RedirectResponse("/schools", status_code=302)

@app.get("/schools/delete/{sid}")
def schools_del(request: Request, sid: int):
    user=get_user(request)
    if not user or user['role']!='admin': return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("DELETE FROM schools WHERE id=?", (sid,)); conn.commit(); conn.close()
    return RedirectResponse("/schools", status_code=302)
