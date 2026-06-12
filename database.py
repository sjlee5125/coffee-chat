from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import socket
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
hostname = socket.gethostname()
if hostname == "coffeechat":
    # 클라우드 서버 내부에서는 옆방 DB로 바로 접속 (localhost)
    SQLALCHEMY_DATABASE_URL = "postgresql://postgres:soldesk0526@localhost:5432/postgres"
else:
    # 팀원들 노트북에서는 클라우드 서버 DB로 원격 접속 (외부 IP)
    SQLALCHEMY_DATABASE_URL = "postgresql://postgres:soldesk0526@48.211.169.52:5432/postgres"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
