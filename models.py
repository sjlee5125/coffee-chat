import enum
from sqlalchemy import create_engine, Column, Integer, String, Text, Enum, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. DB 연결 설정 (우리가 방금 연동 성공한 PostgreSQL 정보로 업데이트)
# pg_hba.conf를 trust로 설정했기 때문에 password 자리에는 아무 값이나 들어가도 접속됩니다!
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:password@48.211.169.52:5432/postgres"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserRole(enum.Enum):
    MENTOR = "mentor"
    MENTEE = "mentee"

class User(Base):
    __tablename__ = "users"
    __table_args__ = {'schema': 'public'}
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True) 
    name = Column(String(100), nullable=False)                        
    password_hash = Column(String(255), nullable=True)                 
    
   
    provider = Column(String(50), default="local")                     
    provider_id = Column(String(255), unique=True, nullable=True)      
    role = Column(Enum(UserRole), default=UserRole.MENTEE)
    
    
    bio = Column(Text, nullable=True)                                  
    mbti = Column(String(4), nullable=True)                            
    hashtags = Column(String(255), nullable=True)                      
    experience = Column(Text, nullable=True)                           
    portfolio_url = Column(Text, nullable=True)                        
    portfolio_file_path = Column(Text, nullable=True)                  
    help_provide = Column(Text, nullable=True)                         
    help_receive = Column(Text, nullable=True)                         
    # 계정 생성일 자동 기록
    created_at = Column(DateTime, server_default=func.now())

# DB 테이블 생성 함수
def create_tables():
    Base.metadata.create_all(bind=engine)

# DB 세션 의존성 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()