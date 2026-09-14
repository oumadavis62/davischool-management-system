import os, hashlib, secrets
from pathlib import Path
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session

BASE = Path(__file__).resolve().parent.parent
DBURL = os.getenv('DATABASE_URL', f'sqlite:///{BASE}/data/school_online.db')
if DBURL.startswith('postgres://'):
    DBURL = DBURL.replace('postgres://','postgresql://',1)
engine = create_engine(DBURL, connect_args={"check_same_thread": False} if "sqlite" in DBURL else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def hash_pwd(p): return hashlib.sha256(p.encode()).hexdigest()
def verify_pwd(p,h): return hash_pwd(p)==h

class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True)
    username=Column(String(80),unique=True)
    password_hash=Column(String(255))
    role=Column(String(30),default='admin')
    active=Column(Boolean,default=True)

Base.metadata.create_all(bind=engine)

def init_data():
    db=SessionLocal()
    try:
        pwd=os.getenv('ADMIN_PASSWORD','Ouma@940')
        admin=db.query(User).filter(User.username=='admin').first()
        if not admin:
            db.add(User(username='admin',password_hash=hash_pwd(pwd),role='admin',active=True))
        else:
            admin.password_hash=hash_pwd(pwd)
        db.commit()
    finally: db.close()
init_data()

def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

app=FastAPI()
app.add_middleware(SessionMiddleware,secret_key=os.getenv('SECRET_KEY','davischool123'))

@app.get('/')
def home(request: Request): return RedirectResponse('/login')

@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return HTMLResponse('<h2>Davi School</h2><form method="post" action="/login">User: <input name="username" value="admin"><br>Pass: <input type="password" name="password" value="Ouma@940"><br><button>Login</button></form>')

@app.post('/login')
def login(request: Request, username: str=Form(...), password: str=Form(...), db: Session=Depends(get_db)):
    user=db.query(User).filter(User.username==username).first()
    if user and verify_pwd(password,user.password_hash):
        request.session['user']=username
        return RedirectResponse('/dashboard',status_code=302)
    return HTMLResponse('Fail <a href="/login">retry</a>',401)

@app.get('/dashboard', response_class=HTMLResponse)
def dashboard(request: Request):
    if not request.session.get('user'): return RedirectResponse('/login')
    return HTMLResponse('<h2>Welcome - Password Ouma@940 Working!</h2><a href="/logout">Logout</a>')

@app.get('/logout')
def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/login')

@app.get('/health')
def health(): return {"status":"ok"}