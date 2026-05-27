import enum
import socket
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    Enum, DateTime, ForeignKey, Date, Boolean, func, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ─── 1. 데이터베이스 연결 설정 ───
hostname = socket.gethostname()
if hostname == "coffeechat":
    # 클라우드 서버 내부 접속 (localhost)
    SQLALCHEMY_DATABASE_URL = "postgresql://postgres:soldesk0526@localhost:5432/postgres"
else:
    # 팀원 노트북 원격 접속 (외부 IP)
    SQLALCHEMY_DATABASE_URL = "postgresql://postgres:soldesk0526@48.211.169.52:5432/postgres"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── 2. 공통 데이터 모델 정의 ───

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
    role = Column(Enum(UserRole), nullable=True, default=UserRole.MENTEE)
    provider = Column(String(50), default="local")                     
    provider_id = Column(String(255), unique=True, nullable=True)      
    bio = Column(Text, nullable=True)                                  
    mbti = Column(String(4), nullable=True)                            
    hashtags = Column(String(255), nullable=True)                      
    experience = Column(Text, nullable=True)                           
    portfolio_url = Column(Text, nullable=True)                        
    portfolio_file_path = Column(Text, nullable=True)                  
    help_provide = Column(Text, nullable=True)                         
    help_receive = Column(Text, nullable=True)                         
    profile_image = Column(Text, nullable=True)
    phone_number = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Mentor(Base):
    __tablename__ = "mentors"
    __table_args__ = {'schema': 'public'}
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, nullable=False) 
    name = Column(String(100), nullable=False)             
    price = Column(String(50), default="10,000 원")
    job_title = Column(String(100), nullable=True)          
    career_history = Column(Text, nullable=True)   
    mentor_intro = Column(Text, nullable=True)             
    mentoring_topics = Column(Text, nullable=True)         
    detailed_experience = Column(Text, nullable=True)      


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = {'schema': 'public'}
    
    id = Column(Integer, primary_key=True, index=True)
    mentor_id = Column(Integer, nullable=False)        
    user_id = Column(Integer, nullable=True)          
    booking_date = Column(Date, nullable=False)        
    booking_time = Column(String(50), nullable=False)  
    questions = Column(Text, nullable=False)           
    status = Column(String(50), default="PAID")        
    created_at = Column(DateTime, server_default=func.now())
    penalty_applied = Column(Boolean, default=False, nullable=False)  
    cancelled_at = Column(DateTime, nullable=True)                    
    cancelled_by = Column(String(10), nullable=True)                  


class MentorAvailability(Base):
    __tablename__ = "mentor_availability"
    __table_args__ = (
        UniqueConstraint('mentor_id', 'date', 'time', name='uq_mentor_date_time'),
        {'schema': 'public'}
    )

    id = Column(Integer, primary_key=True, index=True)
    mentor_id = Column(Integer, nullable=False, index=True)  
    date = Column(Date, nullable=False)                      
    time = Column(String(5), nullable=False)                 
    created_at = Column(DateTime, server_default=func.now()) # 💡 안전한 시간 포맷으로 변경
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Notification(Base):
    """종 모양 알림 정보 보관용 테이블 (중복 라인 제거 및 외래키 정교화 버전)"""
    __tablename__ = "notifications"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('public.users.id'), nullable=False) 
    message = Column(String(255), nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


# ─── 3. DB 헬퍼 및 제너레이터 ───

def create_tables():
    """안전하게 신규 스케줄/알림 스키마 동기화 테이블 생성"""
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    print("테이블 구조 변경사항 반영 및 생성 시작...")
    create_tables()
    print("테이블 생성 및 동기화 작업 완료!")