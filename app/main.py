import os,hashlib,secrets,datetime,sqlite3,io,csv
from pathlib import Path
from typing import Optional
from fastapi import FastAPI,Request,Form,Depends
from fastapi.responses import HTMLResponse,RedirectResponse,StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine,Column,Integer,String,Float,Date,DateTime,Boolean,ForeignKey,Text,func
from sqlalchemy.orm import declarative_base,sessionmaker,Session,relationship

BASE=Path(__file__).resolve().parent.parent
DBURL=os.getenv('DATABASE_URL',f'sqlite:///{BASE}/data/school_online.db')
connect_args={'check_same_thread':False} if DBURL.startswith('sqlite') else {}
engine=create_engine(DBURL,connect_args=connect_args)
SessionLocal=sessionmaker(bind=engine,autocommit=False,autoflush=False)
Base=declarative_base()

def now(): return datetime.datetime.utcnow()
class User(Base):
    __tablename__='users'; id=Column(Integer,primary_key=True); username=Column(String(80),unique=True); password_hash=Column(String(255)); role=Column(String(30),default='admin'); active=Column(Boolean,default=True)
class School(Base):
    __tablename__='school'; id=Column(Integer,primary_key=True); name=Column(String(200),default='My School'); address=Column(String(300),default=''); phone=Column(String(80),default=''); email=Column(String(120),default=''); motto=Column(String(300),default='')
class AcademicYear(Base):
    __tablename__='academic_years'; id=Column(Integer,primary_key=True); name=Column(String(40)); active=Column(Boolean,default=False)
class Term(Base):
    __tablename__='terms'; id=Column(Integer,primary_key=True); name=Column(String(40)); year_id=Column(Integer,ForeignKey('academic_years.id')); active=Column(Boolean,default=False)
class ClassRoom(Base):
    __tablename__='classes'; id=Column(Integer,primary_key=True); name=Column(String(100)); stream=Column(String(100),default=''); teacher_id=Column(Integer,ForeignKey('staff.id'),nullable=True)
class Student(Base):
    __tablename__='students'; id=Column(Integer,primary_key=True); admission_no=Column(String(60),unique=True); first_name=Column(String(100)); last_name=Column(String(100)); gender=Column(String(20)); dob=Column(Date,nullable=True); class_id=Column(Integer,ForeignKey('classes.id')); parent_name=Column(String(150),default=''); parent_phone=Column(String(50),default=''); parent_email=Column(String(120),default=''); address=Column(String(300),default=''); active=Column(Boolean,default=True)
class Staff(Base):
    __tablename__='staff'; id=Column(Integer,primary_key=True); staff_no=Column(String(60),unique=True); name=Column(String(160)); role=Column(String(80)); phone=Column(String(50),default=''); email=Column(String(120),default=''); active=Column(Boolean,default=True)
class Subject(Base):
    __tablename__='subjects'; id=Column(Integer,primary_key=True); code=Column(String(30)); name=Column(String(120)); department=Column(String(100),default=''); active=Column(Boolean,default=True)
class Assessment(Base):
    __tablename__='assessments'; id=Column(Integer,primary_key=True); name=Column(String(120)); kind=Column(String(50),default='Exam'); year_id=Column(Integer,ForeignKey('academic_years.id')); term_id=Column(Integer,ForeignKey('terms.id')); class_id=Column(Integer,ForeignKey('classes.id')); subject_id=Column(Integer,ForeignKey('subjects.id')); max_marks=Column(Float,default=100); weight=Column(Float,default=100); date=Column(Date,default=datetime.date.today); status=Column(String(30),default='Open')
class Mark(Base):
    __tablename__='marks'; id=Column(Integer,primary_key=True); assessment_id=Column(Integer,ForeignKey('assessments.id')); student_id=Column(Integer,ForeignKey('students.id')); marks=Column(Float); entered_by=Column(String(80)); entered_at=Column(DateTime,default=now); remark=Column(String(200),default='')
class Attendance(Base):
    __tablename__='attendance'; id=Column(Integer,primary_key=True); student_id=Column(Integer,ForeignKey('students.id')); date=Column(Date,default=datetime.date.today); status=Column(String(20),default='Present'); note=Column(String(200),default='')
class FeeItem(Base):
    __tablename__='fee_items'; id=Column(Integer,primary_key=True); student_id=Column(Integer,ForeignKey('students.id')); year_id=Column(Integer); term_id=Column(Integer); description=Column(String(160)); amount=Column(Float); created_at=Column(DateTime,default=now)
class Receipt(Base):
    __tablename__='receipts'; id=Column(Integer,primary_key=True); student_id=Column(Integer,ForeignKey('students.id')); amount=Column(Float); method=Column(String(40)); reference=Column(String(100)); date=Column(Date,default=datetime.date.today)
class Timetable(Base):
    __tablename__='timetable'; id=Column(Integer,primary_key=True); class_id=Column(Integer); day=Column(String(20)); period=Column(String(40)); subject_id=Column(Integer); teacher_id=Column(Integer); room=Column(String(80),default='')
class LibraryItem(Base):
    __tablename__='library'; id=Column(Integer,primary_key=True); title=Column(String(200)); author=Column(String(160),default=''); isbn=Column(String(80),default=''); copies=Column(Integer,default=1); available=Column(Integer,default=1)
class InventoryItem(Base):
    __tablename__='inventory'; id=Column(Integer,primary_key=True); name=Column(String(160)); category=Column(String(100),default=''); quantity=Column(Integer,default=0); reorder_level=Column(Integer,default=0); unit_cost=Column(Float,default=0)
class Discipline(Base):
    __tablename__='discipline'; id=Column(Integer,primary_key=True); student_id=Column(Integer); date=Column(Date,default=datetime.date.today); category=Column(String(80)); description=Column(Text); action=Column(Text,default='')
class Message(Base):
    __tablename__='messages'; id=Column(Integer,primary_key=True); recipient=Column(String(160)); phone=Column(String(60)); body=Column(Text); status=Column(String(30),default='Queued'); created_at=Column(DateTime,default=now)
class Audit(Base):
    __tablename__='audit'; id=Column(Integer,primary_key=True); username=Column(String(80)); action=Column(String(250)); created_at=Column(DateTime,default=now)
class GradeScale(Base):
    __tablename__='grading'; id=Column(Integer,primary_key=True); grade=Column(String(10)); min_percent=Column(Float); max_percent=Column(Float); remark=Column(String(120))
Base.metadata.create_all(engine)

def hashpw(p,s=None):
    s=s or secrets.token_hex(16); return s+'$'+hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),180000).hex()
def checkpw(p,h):
    try:s,d=h.split('$',1);return secrets.compare_digest(hashpw(p,s).split('$',1)[1],d)
    except:return False
def seed(db):
    admin_password=os.getenv('ADMIN_PASSWORD','admin123')
    if not db.query(User).first(): db.add(User(username=os.getenv('ADMIN_USERNAME','admin'),password_hash=hashpw(admin_password),role='admin'))
    if not db.query(School).first(): db.add(School(name=os.getenv('SCHOOL_NAME','My School'),motto='Excellence in Education'))
    if not db.query(AcademicYear).first():
        y=AcademicYear(name=str(datetime.date.today().year),active=True);db.add(y);db.flush();db.add_all([Term(name='Term 1',year_id=y.id,active=True),Term(name='Term 2',year_id=y.id),Term(name='Term 3',year_id=y.id)])
    if not db.query(GradeScale).first(): db.add_all([GradeScale(grade='A',min_percent=80,max_percent=100,remark='Excellent'),GradeScale(grade='B',min_percent=70,max_percent=79.99,remark='Very Good'),GradeScale(grade='C',min_percent=60,max_percent=69.99,remark='Good'),GradeScale(grade='D',min_percent=50,max_percent=59.99,remark='Satisfactory'),GradeScale(grade='E',min_percent=0,max_percent=49.99,remark='Needs Improvement')])
    db.commit()
db=SessionLocal();seed(db);db.close()
APP_NAME='DaviSchool Management System'
secret_key=os.getenv('SECRET_KEY')
if not secret_key:
    secret_key=secrets.token_urlsafe(48)
app=FastAPI(title=APP_NAME)
app.add_middleware(SessionMiddleware,secret_key=secret_key,https_only=os.getenv('SESSION_HTTPS','0')=='1',same_site='lax',max_age=60*60*12)
app.mount('/static',StaticFiles(directory=str(BASE/'static')),name='static');templates=Jinja2Templates(directory=str(BASE/'templates'))
def getdb():
    x=SessionLocal()
    try:yield x
    finally:x.close()
def user(request): return request.session.get('user')
def need(request): return user(request)
def audit(db,u,a): db.add(Audit(username=u or 'system',action=a));db.commit()
def grade(db,p):
    g=db.query(GradeScale).filter(GradeScale.min_percent<=p,GradeScale.max_percent>=p).first();return (g.grade,g.remark) if g else ('','')
@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request): return templates.TemplateResponse('login.html',{'request':request})
@app.post('/login')
def login(request:Request,username:str=Form(...),password:str=Form(...),db:Session=Depends(getdb)):
    u=db.query(User).filter_by(username=username,active=True).first()
    if u and checkpw(password,u.password_hash): request.session['user']=u.username;request.session['role']=u.role;return RedirectResponse('/',303)
    return templates.TemplateResponse('login.html',{'request':request,'error':'Invalid username or password'})
@app.get('/logout')
def logout(request:Request): request.session.clear();return RedirectResponse('/login',303)
@app.get('/',response_class=HTMLResponse)
def dashboard(request:Request,db:Session=Depends(getdb)):
    if not need(request):return RedirectResponse('/login',303)
    stats={'students':db.query(Student).count(),'staff':db.query(Staff).count(),'classes':db.query(ClassRoom).count(),'subjects':db.query(Subject).count(),'assessments':db.query(Assessment).count(),'fees':db.query(func.coalesce(func.sum(Receipt.amount),0)).scalar() or 0}
    return templates.TemplateResponse('dashboard.html',{'request':request,'stats':stats,'user':user(request)})
def page(request,title,items,cols,form=None): return templates.TemplateResponse('table.html',{'request':request,'title':title,'items':items,'cols':cols,'form':form,'user':user(request)})
@app.get('/students',response_class=HTMLResponse)
def students(request:Request,db:Session=Depends(getdb)):
    if not need(request):return RedirectResponse('/login',303)
    return page(request,'Students',db.query(Student).order_by(Student.id.desc()).all(),['id','admission_no','first_name','last_name','gender','class_id','parent_name','parent_phone','active'],'student')
@app.post('/students/add')
def add_student(request:Request,admission_no:str=Form(...),first_name:str=Form(...),last_name:str=Form(...),gender:str=Form(''),parent_name:str=Form(''),parent_phone:str=Form(''),db:Session=Depends(getdb)):
    s=Student(admission_no=admission_no,first_name=first_name,last_name=last_name,gender=gender,parent_name=parent_name,parent_phone=parent_phone);db.add(s);db.commit();audit(db,user(request),f'Added student {admission_no}');return RedirectResponse('/students',303)
@app.get('/staff',response_class=HTMLResponse)
def staff(request:Request,db:Session=Depends(getdb)):
    return page(request,'Staff',db.query(Staff).order_by(Staff.id.desc()).all(),['id','staff_no','name','role','phone','email','active'],'staff')
@app.post('/staff/add')
def add_staff(request:Request,staff_no:str=Form(...),name:str=Form(...),role:str=Form('Teacher'),phone:str=Form(''),email:str=Form(''),db:Session=Depends(getdb)):
    db.add(Staff(staff_no=staff_no,name=name,role=role,phone=phone,email=email));db.commit();audit(db,user(request),f'Added staff {staff_no}');return RedirectResponse('/staff',303)
@app.get('/subjects',response_class=HTMLResponse)
def subjects(request:Request,db:Session=Depends(getdb)): return page(request,'Subjects',db.query(Subject).all(),['id','code','name','department','active'],'subject')
@app.post('/subjects/add')
def add_subject(request:Request,code:str=Form(...),name:str=Form(...),department:str=Form(''),db:Session=Depends(getdb)):
    db.add(Subject(code=code,name=name,department=department));db.commit();audit(db,user(request),f'Added subject {name}');return RedirectResponse('/subjects',303)
@app.get('/classes',response_class=HTMLResponse)
def classes(request:Request,db:Session=Depends(getdb)): return page(request,'Classes & Streams',db.query(ClassRoom).all(),['id','name','stream','teacher_id'],'class')
@app.post('/classes/add')
def add_class(request:Request,name:str=Form(...),stream:str=Form(''),db:Session=Depends(getdb)): db.add(ClassRoom(name=name,stream=stream));db.commit();return RedirectResponse('/classes',303)
@app.get('/assessments',response_class=HTMLResponse)
def assessments(request:Request,db:Session=Depends(getdb)): return page(request,'Assessments',db.query(Assessment).order_by(Assessment.id.desc()).all(),['id','name','kind','class_id','subject_id','max_marks','weight','date','status'],'assessment')
@app.post('/assessments/add')
def add_assessment(request:Request,name:str=Form(...),kind:str=Form('Exam'),class_id:int=Form(...),subject_id:int=Form(...),max_marks:float=Form(100),weight:float=Form(100),db:Session=Depends(getdb)):
    y=db.query(AcademicYear).filter_by(active=True).first();t=db.query(Term).filter_by(active=True).first();db.add(Assessment(name=name,kind=kind,class_id=class_id,subject_id=subject_id,max_marks=max_marks,weight=weight,year_id=y.id if y else None,term_id=t.id if t else None));db.commit();return RedirectResponse('/assessments',303)
@app.get('/marks',response_class=HTMLResponse)
def marks(request:Request,assessment_id:int=0,db:Session=Depends(getdb)):
    a=db.get(Assessment,assessment_id) if assessment_id else db.query(Assessment).order_by(Assessment.id.desc()).first()
    if not a:return page(request,'Marks Entry',[],[],'marks')
    students=db.query(Student).filter(Student.class_id==a.class_id,Student.active==True).all(); rows=[]
    for s in students:
        m=db.query(Mark).filter_by(assessment_id=a.id,student_id=s.id).first();rows.append((s,m))
    return templates.TemplateResponse('marks.html',{'request':request,'assessment':a,'rows':rows,'assessments':db.query(Assessment).all(),'user':user(request)})
@app.post('/marks/save')
def save_marks(request:Request,assessment_id:int=Form(...),db:Session=Depends(getdb)):
    a=db.get(Assessment,assessment_id);form=__import__('asyncio').run(request.form());
    for k,v in form.items():
        if k.startswith('s_') and v!='':
            sid=int(k[2:]); val=max(0,min(float(v),a.max_marks));m=db.query(Mark).filter_by(assessment_id=a.id,student_id=sid).first()
            if not m:m=Mark(assessment_id=a.id,student_id=sid);db.add(m)
            m.marks=val;m.entered_by=user(request) or 'system';m.entered_at=now()
    db.commit();audit(db,user(request),f'Saved marks for assessment {a.name}');return RedirectResponse('/marks?assessment_id='+str(a.id),303)
@app.get('/analytics',response_class=HTMLResponse)
def analytics(request:Request,db:Session=Depends(getdb)):
    data=[]
    for a in db.query(Assessment).all():
        vals=[m.marks/a.max_marks*100 for m in db.query(Mark).filter_by(assessment_id=a.id).all() if a.max_marks]
        if vals:data.append({'name':a.name,'average':round(sum(vals)/len(vals),1),'highest':round(max(vals),1),'count':len(vals)})
    return templates.TemplateResponse('analytics.html',{'request':request,'data':data,'user':user(request)})
@app.get('/student-analysis',response_class=HTMLResponse)
def student_analysis(request:Request,student_id:int=0,db:Session=Depends(getdb)):
    s=db.get(Student,student_id) if student_id else db.query(Student).first(); rows=[]
    if s:
        for m in db.query(Mark).filter_by(student_id=s.id).all():
            a=db.get(Assessment,m.assessment_id);p=(m.marks/a.max_marks*100) if a and a.max_marks else 0;g,r=grade(db,p);rows.append({'assessment':a.name if a else '', 'percent':round(p,1),'grade':g,'remark':r})
    return templates.TemplateResponse('student_analysis.html',{'request':request,'student':s,'rows':rows,'students':db.query(Student).all(),'user':user(request)})
@app.get('/report-card',response_class=HTMLResponse)
def report_card(request:Request,student_id:int=0,db:Session=Depends(getdb)):
    s=db.get(Student,student_id) if student_id else db.query(Student).first();rows=[];avg=0
    if s:
        for m in db.query(Mark).filter_by(student_id=s.id).all():
            a=db.get(Assessment,m.assessment_id);p=(m.marks/a.max_marks*100) if a and a.max_marks else 0;g,r=grade(db,p);rows.append((a,m,p,g,r));
        avg=sum(x[2] for x in rows)/len(rows) if rows else 0
    g,r=grade(db,avg)
    return templates.TemplateResponse('report.html',{'request':request,'student':s,'rows':rows,'avg':round(avg,1),'grade':g,'remark':r,'students':db.query(Student).all(),'school':db.query(School).first(),'user':user(request)})
@app.get('/attendance',response_class=HTMLResponse)
def attendance(request:Request,db:Session=Depends(getdb)): return page(request,'Attendance',db.query(Attendance).order_by(Attendance.date.desc()).limit(300).all(),['id','student_id','date','status','note'],'attendance')
@app.post('/attendance/add')
def add_att(request:Request,student_id:int=Form(...),status:str=Form('Present'),note:str=Form(''),db:Session=Depends(getdb)):db.add(Attendance(student_id=student_id,status=status,note=note));db.commit();return RedirectResponse('/attendance',303)
@app.get('/finance',response_class=HTMLResponse)
def finance(request:Request,db:Session=Depends(getdb)):
    receipts=db.query(Receipt).order_by(Receipt.date.desc()).all();return page(request,'Finance & Fees',receipts,['id','student_id','amount','method','reference','date'],'receipt')
@app.post('/finance/receipt')
def receipt(request:Request,student_id:int=Form(...),amount:float=Form(...),method:str=Form('Cash'),reference:str=Form(''),db:Session=Depends(getdb)):db.add(Receipt(student_id=student_id,amount=amount,method=method,reference=reference));db.commit();return RedirectResponse('/finance',303)
@app.get('/library',response_class=HTMLResponse)
def library(request:Request,db:Session=Depends(getdb)):return page(request,'Library',db.query(LibraryItem).all(),['id','title','author','isbn','copies','available'],'library')
@app.post('/library/add')
def library_add(request:Request,title:str=Form(...),author:str=Form(''),isbn:str=Form(''),copies:int=Form(1),db:Session=Depends(getdb)):db.add(LibraryItem(title=title,author=author,isbn=isbn,copies=copies,available=copies));db.commit();return RedirectResponse('/library',303)
@app.get('/inventory',response_class=HTMLResponse)
def inventory(request:Request,db:Session=Depends(getdb)):return page(request,'Inventory',db.query(InventoryItem).all(),['id','name','category','quantity','reorder_level','unit_cost'],'inventory')
@app.post('/inventory/add')
def inventory_add(request:Request,name:str=Form(...),category:str=Form(''),quantity:int=Form(0),reorder_level:int=Form(0),unit_cost:float=Form(0),db:Session=Depends(getdb)):db.add(InventoryItem(name=name,category=category,quantity=quantity,reorder_level=reorder_level,unit_cost=unit_cost));db.commit();return RedirectResponse('/inventory',303)
@app.get('/discipline',response_class=HTMLResponse)
def discipline(request:Request,db:Session=Depends(getdb)):return page(request,'Discipline',db.query(Discipline).order_by(Discipline.date.desc()).all(),['id','student_id','date','category','description','action'],'discipline')
@app.post('/discipline/add')
def discipline_add(request:Request,student_id:int=Form(...),category:str=Form(...),description:str=Form(...),action:str=Form(''),db:Session=Depends(getdb)):db.add(Discipline(student_id=student_id,category=category,description=description,action=action));db.commit();return RedirectResponse('/discipline',303)
@app.get('/timetable',response_class=HTMLResponse)
def timetable(request:Request,db:Session=Depends(getdb)):return page(request,'Timetable',db.query(Timetable).all(),['id','class_id','day','period','subject_id','teacher_id','room'],'timetable')
@app.get('/messages',response_class=HTMLResponse)
def messages(request:Request,db:Session=Depends(getdb)):return page(request,'Parent Messaging',db.query(Message).order_by(Message.id.desc()).all(),['id','recipient','phone','body','status','created_at'],'message')
@app.post('/messages/add')
def message_add(request:Request,recipient:str=Form(...),phone:str=Form(...),body:str=Form(...),db:Session=Depends(getdb)):db.add(Message(recipient=recipient,phone=phone,body=body));db.commit();return RedirectResponse('/messages',303)
@app.get('/reports/export/students')
def export_students(request:Request,db:Session=Depends(getdb)):
    out=io.StringIO();w=csv.writer(out);w.writerow(['Admission No','First Name','Last Name','Gender','Parent','Phone']);
    for s in db.query(Student).all():w.writerow([s.admission_no,s.first_name,s.last_name,s.gender,s.parent_name,s.parent_phone])
    return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=students.csv'})
@app.get('/settings',response_class=HTMLResponse)
def settings(request:Request,db:Session=Depends(getdb)):return page(request,'School Settings',db.query(School).all(),['id','name','address','phone','email','motto'],'settings')
@app.post('/settings/save')
def settings_save(request:Request,name:str=Form(...),address:str=Form(''),phone:str=Form(''),email:str=Form(''),motto:str=Form(''),db:Session=Depends(getdb)):
    s=db.query(School).first() or School();s.name=name;s.address=address;s.phone=phone;s.email=email;s.motto=motto;db.add(s);db.commit();return RedirectResponse('/settings',303)
@app.get('/admin',response_class=HTMLResponse)
def admin(request:Request,db:Session=Depends(getdb)):return page(request,'Administration / Audit Log',db.query(Audit).order_by(Audit.id.desc()).limit(500).all(),['id','username','action','created_at'],'admin')
