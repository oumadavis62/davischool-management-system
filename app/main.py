import sqlite3, os, hashlib
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
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
    conn = get_db(); c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, code TEXT UNIQUE, password_hash TEXT, role TEXT DEFAULT 'school')")
    c.execute("CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, stream TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, school_id INTEGER, adm_no TEXT, name TEXT, class_id INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, teacher TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY, school_id INTEGER, name TEXT, term TEXT, year INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS timetable (id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER, day TEXT, period INTEGER, subject_id INTEGER, teacher TEXT)")
    c.execute("SELECT * FROM schools WHERE code='ADMIN001'")
    if not c.fetchone():
        ph = hashlib.sha256("Admin@2026".encode()).hexdigest()
        c.execute("INSERT INTO schools (name,code,password_hash,role) VALUES (?,?,?,?)", ("Admin","ADMIN001",ph,"admin"))
    conn.commit(); conn.close()

init_db()
def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()
def check_pw(p,h): return hash_pw(p)==h
def get_user(request: Request):
    token = request.cookies.get("session")
    if not token: return None
    try: return serializer.loads(token, max_age=86400)
    except: return None

DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday"]
PERIODS = [1,2,3,4,5,6,7,8]

def layout(title, body, user=None):
    nav=""
    if user:
        if user['role']=='admin':
            nav='<a href="/dashboard">Dashboard</a> | <a href="/schools">Schools</a> | <a href="/logout">Logout</a>'
        else:
            nav='<a href="/dashboard">Dashboard</a> | <a href="/students">Students</a> | <a href="/classes">Classes</a> | <a href="/subjects">Subjects</a> | <a href="/exams">Exams</a> | <a href="/timetable">Timetable ASC</a> | <a href="/logout">Logout</a>'
    html = "<html><head><title>" + title + "</title><style>"
    html += "body{font-family:Arial;margin:0;background:#f4f6f9}.top{background:#1a237e;color:white;padding:12px 20px;display:flex;justify-content:space-between}.top a{color:white;text-decoration:none;margin-right:12px}.container{padding:20px}.card{background:white;padding:16px;border-radius:8px;box-shadow:0 2px 6px rgba(0,0,0,0.1);margin-bottom:16px} table{width:100%;border-collapse:collapse} th,td{border:1px solid #ccc;padding:6px;font-size:14px} th{background:#e8eaf6}.btn{background:#3949ab;color:white;padding:6px 12px;border:none;border-radius:4px;cursor:pointer;text-decoration:none}.btn-red{background:#c62828}.wall td{height:52px;min-width:110px}.slot{background:#e3f2fd;border-radius:4px;padding:3px;font-size:12px}.conflict{background:#ffcdd2;border:1px solid red} @media print{.top,.no-print{display:none}}"
    html += "</style></head><body><div class='top'><div><b>DaviSchool</b></div><div>" + nav + "</div></div><div class='container'><h2>" + title + "</h2>" + body + "</div></body></html>"
    return html

@app.get("/", response_class=HTMLResponse)
def home(): return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
def login_page():
    body='<div class="card" style="max-width:400px;margin:auto"><form method="post" action="/login"><label>Code</label><br><input name="code" required style="width:100%;padding:8px"><br><br><label>Password</label><br><input type="password" name="password" required style="width:100%;padding:8px"><br><br><button class="btn" type="submit">Login</button></form></div>'
    return HTMLResponse(layout("Login", body))

@app.post("/login")
def do_login(request: Request, code: str = Form(...), password: str = Form(...)):
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM schools WHERE code=?", (code,))
    sch=c.fetchone()
    if sch and check_pw(password, sch["password_hash"]):
        data={"school_id":sch["id"],"role":sch["role"],"name":sch["name"],"code":sch["code"]}
        token=serializer.dumps(data)
        conn.close()
        resp=RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("session", token, httponly=True)
        return resp
    conn.close()
    return HTMLResponse(layout("Login", '<div class="card"><p style="color:red">Invalid</p><a href="/login">Back</a></div>'))

@app.get("/logout")
def logout():
    r=RedirectResponse("/login"); r.delete_cookie("session"); return r

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    if user['role']=='admin':
        c.execute("SELECT COUNT(*) as cnt FROM schools WHERE role!='admin'"); sc=c.fetchone()["cnt"]
        body="<div class='card'>Admin - Schools: " + str(sc) + "</div><div class='card'><a class='btn' href='/schools'>Manage Schools</a></div>"
    else:
        sid=user['school_id']
        c.execute("SELECT COUNT(*) as cnt FROM students WHERE school_id=?", (sid,)); stu=c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM classes WHERE school_id=?", (sid,)); cls=c.fetchone()["cnt"]
        body="<div class='card'>Welcome " + user['name'] + " Students:" + str(stu) + " Classes:" + str(cls) + "</div>"
        body+="<div class='card'><a class='btn' href='/students'>Students</a> <a class='btn' href='/classes'>Classes</a> <a class='btn' href='/subjects'>Subjects</a> <a class='btn' href='/exams'>Exams</a> <a class='btn' href='/timetable' style='background:#00897b'>Timetable ASC</a></div>"
    conn.close()
    return HTMLResponse(layout("Dashboard", body, user))

@app.get("/schools", response_class=HTMLResponse)
def schools_page(request: Request):
    user=get_user(request)
    if not user or user['role']!='admin': return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor(); c.execute("SELECT * FROM schools WHERE role!='admin'"); rows=c.fetchall()
    tr=""
    for r in rows: tr+="<tr><td>" + r['name'] + "</td><td>" + r['code'] + "</td><td><a href='/schools/delete/" + str(r['id']) + "' class='btn btn-red'>Del</a></td></tr>"
    body="<div class='card'><form method='post' action='/schools/add'><input name='name' placeholder='School Name' required><input name='code' placeholder='Code' required><input name='password' placeholder='Password' required><button class='btn'>Add</button></form></div><div class='card'><table><tr><th>Name</th><th>Code</th><th>Act</th></tr>" + tr + "</table></div>"
    conn.close()
    return HTMLResponse(layout("Schools", body, user))

@app.post("/schools/add")
def schools_add(request: Request, name: str=Form(...), code: str=Form(...), password: str=Form(...)):
    user=get_user(request)
    if not user or user['role']!='admin': return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    try:
        c.execute("INSERT INTO schools (name,code,password_hash,role) VALUES (?,?,?,?)", (name,code,hash_pw(password),"school")); conn.commit()
    except: pass
    conn.close()
    return RedirectResponse("/schools", status_code=302)

@app.get("/classes", response_class=HTMLResponse)
def classes_page(request: Request):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    sid=user['school_id'] if user['role']!='admin' else None
    conn=get_db(); c=conn.cursor()
    if sid: c.execute("SELECT * FROM classes WHERE school_id=?", (sid,))
    else: c.execute("SELECT * FROM classes")
    rows=c.fetchall()
    tr="".join(["<tr><td>" + r['name'] + " " + (r['stream'] or "") + "</td></tr>" for r in rows])
    form=""
    if user['role']!='admin': form="<div class='card'><form method='post' action='/classes/add'><input name='name' placeholder='Class' required><input name='stream' placeholder='Stream'><button class='btn'>Add</button></form></div>"
    body=form + "<div class='card'><table><tr><th>Class</th></tr>" + tr + "</table></div>"
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
    c.execute("SELECT s.*, c.name as cname FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.school_id=?", (user['school_id'],))
    rows=c.fetchall()
    tr="".join(["<tr><td>" + r['adm_no'] + "</td><td>" + r['name'] + "</td><td>" + (r['cname'] or "") + "</td></tr>" for r in rows])
    c.execute("SELECT * FROM classes WHERE school_id=?", (user['school_id'],)); cls=c.fetchall()
    opts="".join(["<option value='" + str(cl['id']) + "'>" + cl['name'] + " " + (cl['stream'] or "") + "</option>" for cl in cls])
    body="<div class='card'><form method='post' action='/students/add'><input name='adm_no' placeholder='Adm No' required><input name='name' placeholder='Name' required><select name='class_id'>" + opts + "</select><button class='btn'>Add</button></form></div><div class='card'><table><tr><th>Adm</th><th>Name</th><th>Class</th></tr>" + tr + "</table></div>"
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
    tr="".join(["<tr><td>" + r['name'] + "</td><td>" + (r['teacher'] or "") + "</td></tr>" for r in rows])
    body="<div class='card'><form method='post' action='/subjects/add'><input name='name' placeholder='Subject' required><input name='teacher' placeholder='Teacher'><button class='btn'>Add</button></form></div><div class='card'><table><tr><th>Subject</th><th>Teacher</th></tr>" + tr + "</table></div>"
    conn.close()
    return HTMLResponse(layout("Subjects", body, user))

@app.post("/subjects/add")
def subjects_add(request: Request, name: str=Form(...), teacher: str=Form(...)):
    user=get_user(request)
    conn=get_db(); c=conn.cursor()
    c.execute("INSERT INTO subjects (school_id,name,teacher) VALUES (?,?,?)", (user['school_id'],name,teacher)); conn.commit(); conn.close()
    return RedirectResponse("/subjects", status_code=302)

@app.get("/exams", response_class=HTMLResponse)
def exams_page(request: Request):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor(); c.execute("SELECT * FROM exams WHERE school_id=?", (user['school_id'],)); rows=c.fetchall()
    tr="".join(["<tr><td>" + r['name'] + "</td><td>" + (r['term'] or "") + "</td></tr>" for r in rows])
    body="<div class='card'><form method='post' action='/exams/add'><input name='name' placeholder='Exam' required><input name='term' placeholder='Term'><input name='year' placeholder='2026'><button class='btn'>Add</button></form></div><div class='card'><table><tr><th>Exam</th><th>Term</th></tr>" + tr + "</table></div>"
    conn.close()
    return HTMLResponse(layout("Exams", body, user))

@app.post("/exams/add")
def exams_add(request: Request, name: str=Form(...), term: str=Form(...), year: int=Form(...)):
    user=get_user(request)
    conn=get_db(); c=conn.cursor()
    c.execute("INSERT INTO exams (school_id,name,term,year) VALUES (?,?,?,?)", (user['school_id'],name,term,year)); conn.commit(); conn.close()
    return RedirectResponse("/exams", status_code=302)

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
        class_opts+="<option value='" + str(cl['id']) + "' " + sel + ">" + cl['name'] + " " + (cl['stream'] or "") + "</option>"
    sub_opts=""
    for s in subjects:
        sub_opts+="<option value='" + str(s['id']) + "'>" + s['name'] + " (" + (s['teacher'] or "") + ")</option>"

    grid="<table class='wall'><tr><th>Period</th>"
    for d in DAYS: grid+="<th>" + d + "</th>"
    grid+="</tr>"
    for p in PERIODS:
        grid+="<tr><th>P" + str(p) + "</th>"
        for d in DAYS:
            key=(d,p)
            if key in tt_map:
                rec=tt_map[key]
                sub=sub_map.get(rec['subject_id'])
                sname=sub['name'] if sub else "?"
                teacher=rec['teacher']
                is_conf=(d,p,teacher) in conflict_set
                cls_name="slot conflict" if is_conf else "slot"
                grid+="<td><div class='" + cls_name + "'><b>" + sname + "</b><br><small>" + teacher + "</small><br><a href='/timetable/delete/" + str(rec['id']) + "?class_id=" + str(class_id) + "' class='no-print' style='color:red;font-size:10px'>x</a></div></td>"
            else:
                grid+="<td></td>"
        grid+="</tr>"
    grid+="</table>"

    teacher_html=""
    if view=="teacher":
        teacher_html="<table><tr><th>Teacher</th>"
        for d in DAYS: teacher_html+="<th>" + d + "</th>"
        teacher_html+="</tr>"
        teachers=list(set([r['teacher'] for r in all_tt if r['teacher']]))
        for tch in teachers:
            teacher_html+="<tr><td><b>" + tch + "</b></td>"
            for d in DAYS:
                cells=[]
                for r in all_tt:
                    if r['teacher']==tch and r['day']==d:
                        cl_name=next((cl['name']+" "+(cl['stream'] or "") for cl in classes if cl['id']==r['class_id']), "?")
                        sub=sub_map.get(r['subject_id'])
                        sname=sub['name'] if sub else "?"
                        cells.append(sname+"@"+cl_name+" P"+str(r['period']))
                teacher_html+="<td><small>" + "<br>".join(cells) + "</small></td>"
            teacher_html+="</tr>"
        teacher_html+="</table>"

    view_sel_class="selected" if view=="class" else ""
    view_sel_teacher="selected" if view=="teacher" else ""

    body="<div class='card no-print'><form method='get' action='/timetable' style='display:flex;gap:8px;flex-wrap:wrap'><select name='class_id'>" + class_opts + "</select><select name='view'><option value='class' " + view_sel_class + ">Class WallMaster (ASC)</option><option value='teacher' " + view_sel_teacher + ">Teacher View</option></select><button class='btn'>View</button><button class='btn' type='button' onclick='window.print()' style='background:#2e7d32'>Print Poster</button></form></div>"
    body+="<div class='card no-print'><h4>Add Slot (ASC Format)</h4><form method='post' action='/timetable/add'><input type='hidden' name='class_id' value='" + str(class_id) + "'><select name='day' required>"
    for d in DAYS: body+="<option>" + d + "</option>"
    body+="</select><select name='period' required>"
    for p in PERIODS: body+="<option value='" + str(p) + "'>Period " + str(p) + "</option>"
    body+="</select><select name='subject_id' required>" + sub_opts + "</select><input name='teacher' placeholder='Teacher Name' required><button class='btn'>Add Slot</button></form><small>If teacher double-booked same day+period, RED like aSc.</small></div>"
    body+="<div class='card'><h3>ASC Timetable - Class ID " + str(class_id) + "</h3>"
    if view=="class": body+=grid
    else: body+=teacher_html
    body+="</div>"
    body+="<div class='card no-print'><h4>Conflicts: " + str(len(conflicts)) + "</h4><ul>"
    if conflicts:
        for cf in conflicts: body+="<li style='color:red'>" + cf['teacher'] + " double booked " + cf['day'] + " P" + str(cf['period']) + "</li>"
    else: body+="<li>No conflicts</li>"
    body+="</ul></div>"

    conn.close()
    return HTMLResponse(layout("Timetable ASC Format", body, user))

@app.post("/timetable/add")
def timetable_add(request: Request, class_id: int=Form(...), day: str=Form(...), period: int=Form(...), subject_id: int=Form(...), teacher: str=Form(...)):
    user=get_user(request)
    if not user: return RedirectResponse("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("INSERT INTO timetable (school_id,class_id,day,period,subject_id,teacher) VALUES (?,?,?,?,?,?)", (user['school_id'],class_id,day,period,subject_id,teacher))
    conn.commit(); conn.close()
    return RedirectResponse("/timetable?class_id=" + str(class_id), status_code=302)

@app.get("/timetable/delete/{tid}")
def timetable_del(request: Request, tid: int, class_id: int=0):
    user=get_user(request)
    conn=get_db(); c=conn.cursor()
    c.execute("DELETE FROM timetable WHERE id=? AND school_id=?", (tid, user['school_id']))
    conn.commit(); conn.close()
    return RedirectResponse("/timetable?class_id=" + str(class_id), status_code=302)
