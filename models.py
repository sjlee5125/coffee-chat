import enum
import socket
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Text,
    Enum, DateTime, ForeignKey, Date, Boolean, func, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker,relationship
from sqlalchemy import Column, Integer, String,DateTime, UniqueConstraint, Text
from sqlalchemy.sql import func
from database import Base


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
    mentor_profile = relationship("Mentor", backref="user_ref", uselist=False)    
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
    status = Column(String(50), nullable=True)        # '현직자', '취준생' 등
    main_category = Column(String(100), nullable=True) # '개발/엔지니어링'
    sub_category = Column(String(100), nullable=True)  # '백엔드' 등      
    views = Column(Integer, default=0, nullable=False)
    user_id = Column(Integer, ForeignKey("public.users.id"), unique=True, nullable=False)
class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = {'schema': 'public'}
    
    id = Column(Integer, primary_key=True, index=True)
    mentor_id = Column(Integer, ForeignKey("public.mentors.id")) # 💡 public. 추가
    user_id = Column(Integer, ForeignKey("public.users.id"))     # 💡 public. 추가
    booking_date = Column(Date)
    booking_time = Column(String)
    questions = Column(String)
    status = Column(String, default="PAID")        
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
    __tablename__ = "notifications"
    __table_args__ = {'schema': 'public'} # 🌟 1. public 소속 추가!

    id = Column(Integer, primary_key=True, index=True)
    # 🌟 2. users.id -> public.users.id 로 정확한 주소 명시!
    user_id = Column(Integer, ForeignKey("public.users.id", ondelete="CASCADE")) 
    message = Column(String(255)) 
    is_read = Column(Boolean, default=False) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, nullable=True)
    mentor_id = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    stt_text = Column(Text, nullable=True)
    ai_summary = Column(Text, nullable=True)
    status = Column(String(20), default="READY")
    created_at = Column(DateTime, server_default=func.now())

class SavedMentor(Base):
    """멘티가 관심(찜)한 멘토 목록"""
    __tablename__ = "saved_mentors"
    __table_args__ = (
        UniqueConstraint('user_id', 'mentor_id', name='uq_saved_mentor'),
        {'schema': 'public'}
    )
 
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, nullable=False, index=True)   # 찜한 사람 (users.id)
    mentor_id  = Column(Integer, nullable=False, index=True)   # 찜 대상  (mentors.id)
    created_at = Column(DateTime, server_default=func.now())

# ─── 3. DB 헬퍼 및 제너레이터 ───
class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = {'schema': 'public'}
    
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, nullable=False) 
    mentor_id = Column(Integer, nullable=False)  
    user_id = Column(Integer, nullable=False)    
    rating = Column(Integer, nullable=False)      
    # 💡 아래 한 줄을 추가하세요! (글을 안 남기는 사람도 있으니 nullable=True)
    content = Column(Text, nullable=True) 
    created_at = Column(DateTime, server_default=func.now())
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



