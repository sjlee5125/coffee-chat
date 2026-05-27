import enum
from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    Enum, DateTime, Date, Boolean, func, UniqueConstraint  # Boolean, UniqueConstraint 추가
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

import socket
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

# ==========================================
# 2. 공통 ENUM 및 데이터 모델(테이블) 정의
# ==========================================

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
    
    # [추가] 회원가입 시 선택한 유저의 권한/역할 지정
    role = Column(Enum(UserRole), nullable=True, default=UserRole.MENTEE)
    
    # 소셜 로그인 연동 관련 컬럼
    provider = Column(String(50), default="local")                     
    provider_id = Column(String(255), unique=True, nullable=True)      
   
    # 프로필 정보 컬럼 세트
    bio = Column(Text, nullable=True)                                  
    mbti = Column(String(4), nullable=True)                            
    hashtags = Column(String(255), nullable=True)                      
    experience = Column(Text, nullable=True)                           
    portfolio_url = Column(Text, nullable=True)                        
    portfolio_file_path = Column(Text, nullable=True)                  
    help_provide = Column(Text, nullable=True)                         
    help_receive = Column(Text, nullable=True)                         
    
    # [추가] 프론트엔드에서 Base64 텍스트로 넘어오는 인코딩된 프로필 이미지 저장
    profile_image = Column(Text, nullable=True)
    phone_number = Column(String(20), nullable=True)

    created_at = Column(DateTime, server_default=func.now())

class Mentor(Base):
    __tablename__ = "mentors"
    __table_args__ = {'schema': 'public'}
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, nullable=False) # Users 테이블과 연결고리
    name = Column(String(100), nullable=False)             # 공유 데이터
    price = Column(String(50), default="10,000 원")
    
    # 💡 새로 설계한 분리형 컬럼들 매핑
    job_title = Column(String(100), nullable=True)          
    career_history = Column(Text, nullable=True)           # 주요 경력  
    mentor_intro = Column(Text, nullable=True)             # 성장 스토리 에
    mentoring_topics = Column(Text, nullable=True)         # 대화 주제 
    detailed_experience = Column(Text, nullable=True)      # 경험 상세 

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

    # [추가] 멘토 귀책 취소(패널티) 관련 컬럼
    penalty_applied = Column(Boolean, default=False, nullable=False)  # 패널티 부여 여부
    cancelled_at = Column(DateTime, nullable=True)                    # 취소 처리 시각
    cancelled_by = Column(String(10), nullable=True)                  # "mentor" | "mentee"

# ==========================================
# [신규] 멘토 가용 시간 테이블
# ==========================================

class MentorAvailability(Base):
    """
    멘토가 ScheduleManager에서 설정한 '가능 시간' 슬롯을 저장합니다.
    - 프론트의 'available' 상태 슬롯과 1:1 대응
    - 멘티가 예약하면 Booking 테이블에 기록되고, 이 테이블의 해당 행은 삭제됩니다.
    - (mentor_id, date, time) 조합은 유일해야 합니다.
    """
    __tablename__ = "mentor_availability"
    __table_args__ = (
        UniqueConstraint('mentor_id', 'date', 'time', name='uq_mentor_date_time'),
        {'schema': 'public'}
    )

    id = Column(Integer, primary_key=True, index=True)
    mentor_id = Column(Integer, nullable=False, index=True)  # Mentor.id 참조
    date = Column(Date, nullable=False)                      # 예: 2026-05-23
    time = Column(String(5), nullable=False)                 # 예: "09:00" (HH:MM)
   created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

# ==========================================
# 3. DB 헬퍼 함수 및 세션 의존성 정의
# ==========================================

def create_tables():
    """데이터베이스 유실 없이 새로 추가된 스키마/테이블만 안전하게 생성합니다."""
    Base.metadata.create_all(bind=engine)

def get_db():
    """FastAPI 엔드포인트에서 공통으로 사용할 DB 세션 제너레이터입니다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 스크립트 단독 실행 시 테이블 자동 생성 유도 (인덴트 외부 격리 완료)
if __name__ == "__main__":
    print("테이블 구조 변경사항 반영 및 생성 시작...")
    create_tables()
    print("테이블 생성 및 동기화 작업 완료!")
