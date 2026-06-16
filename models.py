import enum
import socket
from datetime import datetime
from sqlalchemy import (
    create_engine, JSON, Column, Integer, String, Boolean, Text,
    Enum, DateTime, ForeignKey, Date, Boolean, func, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker,relationship
from sqlalchemy import Column, Integer, String,DateTime, UniqueConstraint, Text,JSON
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
    ADMIN = "admin"

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
    is_mentor_entered = Column(Boolean, default=False)
    is_mentee_entered = Column(Boolean, default=False)

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
    recommended_questions = Column(JSON, nullable=True)

class CoffeeChatReport(Base):
    """커피챗 종료 후 생성되는 AI 요약 리포트 리포지토리"""
    __tablename__ = "coffee_chat_reports"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    
    # ChatSession 테이블과의 1:1 매칭 제약조건 및 종속 삭제 설정
    chatsession_id = Column(Integer, ForeignKey("public.chat_sessions.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # 서비스 안정성을 위한 멘토/멘티 외래키 연결
    mentor_id = Column(Integer, ForeignKey("public.mentors.id"), nullable=False)
    mentee_id = Column(Integer, ForeignKey("public.users.id"), nullable=False)
    
    # 텍스트 데이터 보관용 대용량 필드
    stt_masked = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    ai_advice = Column(Text, nullable=True)
    
    # 타임스탬프 자동화 
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    masking_map = Column(JSON, nullable=True)

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

class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = {'schema': 'public'}
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    # 관리자 작성자 ID (관리자만 작성할 수 있으므로 참조)
    author_id = Column(Integer, ForeignKey("public.users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    

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
    review = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
def create_tables():
    """안전하게 신규 스케줄/알림 스키마 동기화 테이블 생성"""
    Base.metadata.create_all(bind=engine)


# ─── FAQ 테이블 ───────────────────────────────────────────────────────────────
class FAQ(Base):
    """
    자주 묻는 질문 (FAQ) 저장 테이블
    - 챗봇 RAG 검색용으로 활용 가능
    - category 필드로 카테고리 필터링 지원
    - embedding_text: 향후 벡터 임베딩 원본 저장용 (question + answer 합본)
    """
    __tablename__ = "faqs"
    __table_args__ = {'schema': 'public'}
 
    id             = Column(Integer, primary_key=True, index=True)
    category       = Column(String(50), nullable=False, index=True)   # 예약/결제, 환불, 멘토링, 계정
    question       = Column(Text, nullable=False)                     # 질문
    answer         = Column(Text, nullable=False)                     # 답변
    embedding_text = Column(Text, nullable=True)                      # RAG용: question + " " + answer
    is_active      = Column(Boolean, default=True, nullable=False)    # 노출 여부 (비활성화 소프트 삭제)
    sort_order     = Column(Integer, default=0, nullable=False)       # 같은 카테고리 내 노출 순서
    created_at     = Column(DateTime, server_default=func.now())
    updated_at     = Column(DateTime, server_default=func.now(), onupdate=func.now())
 
 
# ─── 1:1 문의 테이블 ──────────────────────────────────────────────────────────
class InquiryStatus(enum.Enum):
    PENDING    = "pending"     # 접수됨 (미답변)
    IN_REVIEW  = "in_review"   # 검토 중
    ANSWERED   = "answered"    # 답변 완료
    CLOSED     = "closed"      # 종료
 
 
class Inquiry(Base):
    """
    1:1 문의 저장 테이블
    - 비회원 문의도 허용 (user_id nullable)
    - answered_at / answered_by 로 답변 이력 추적
    - admin_note: 내부 메모 (고객에게 미노출)
    """
    __tablename__ = "inquiries"
    __table_args__ = {'schema': 'public'}
 
    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True, index=True)
    category      = Column(String(50), nullable=False)                # 예약/결제, 환불, 멘토링 문제, 계정, 기타
    title         = Column(String(200), nullable=False)               # 제목
    body          = Column(Text, nullable=False)                      # 문의 내용
    email         = Column(String(255), nullable=False)               # 답변받을 이메일
    status = Column(
    Enum(InquiryStatus, values_callable=lambda x: [e.value for e in x]),  # ← 이 줄 추가
    default=InquiryStatus.PENDING,
    nullable=False,
    index=True
)
    answer        = Column(Text, nullable=True)                       # 관리자 답변
    answered_at   = Column(DateTime, nullable=True)                   # 답변 일시
    answered_by   = Column(Integer, ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)  # 답변한 관리자 user_id
    admin_note    = Column(Text, nullable=True)                       # 내부 메모 (고객 비노출)
    created_at    = Column(DateTime, server_default=func.now())
    updated_at    = Column(DateTime, server_default=func.now(), onupdate=func.now())
 
 
# ─── FAQ 초기 데이터 시드 함수 ───────────────────────────────────────────────
def seed_faqs(db):
    """
    프론트 DEFAULT_FAQS 데이터를 DB에 시드.
    이미 데이터가 있으면 스킵.
    """
    if db.query(FAQ).count() > 0:
        print("FAQ 데이터가 이미 존재합니다. 시드를 건너뜁니다.")
        return
 
    initial_faqs = [
        FAQ(category="예약/결제", sort_order=1,
            question="커피챗 세션을 예약하려면 어떻게 하나요?",
            answer="멘토 탐색 페이지에서 원하는 멘토를 선택한 후, 프로필 하단의 '커피챗 예약' 버튼을 클릭하세요. "
                   "날짜 선택 → 질문 작성 → 결제 순서로 진행됩니다. 결제가 완료되면 예약 확인 이메일이 발송됩니다."),
        FAQ(category="예약/결제", sort_order=2,
            question="결제 수단은 어떤 것이 지원되나요?",
            answer="신용카드(VISA, Mastercard, 국내 카드사 전체), 카카오페이, 네이버페이, 토스페이를 지원합니다. "
                   "기업 계좌이체는 별도 문의를 통해 진행하실 수 있습니다."),
        FAQ(category="예약/결제", sort_order=3,
            question="세션 일정을 변경할 수 있나요?",
            answer="세션 시작 48시간 전까지 '커피챗 관리' 페이지에서 일정 변경을 요청할 수 있습니다. "
                   "변경은 멘토의 수락이 필요하며, 수락 후 새 일정으로 확정됩니다."),
        FAQ(category="환불", sort_order=1,
            question="예약 취소 및 환불 정책이 어떻게 되나요?",
            answer="세션 시작 48시간 전까지 취소 시 100% 환불됩니다. 24~48시간 전 취소 시 50% 환불, "
                   "24시간 이내 취소는 환불이 불가합니다. 멘토 사정으로 인한 취소는 항상 100% 환불됩니다."),
        FAQ(category="멘토링", sort_order=1,
            question="커피챗 세션은 얼마나 진행되나요?",
            answer="기본 세션은 30분이며, 멘토에 따라 60분 옵션도 제공됩니다. "
                   "세션 시작 5분 전에 입장 링크가 발송되며, 예약 시간 이후에는 자동으로 세션이 시작됩니다."),
        FAQ(category="멘토링", sort_order=2,
            question="멘토가 세션에 나타나지 않으면 어떻게 하나요?",
            answer="세션 시작 후 10분이 지나도 멘토가 입장하지 않을 경우, 고객센터 채팅으로 즉시 알려주세요. "
                   "전액 환불 또는 다른 멘토와의 세션을 우선 배정해드립니다."),
        FAQ(category="계정", sort_order=1,
            question="멘토로 등록하려면 어떤 조건이 필요한가요?",
            answer="해당 분야 3년 이상의 경력 또는 현직 종사자이면 신청 가능합니다. "
                   "프로필 검토 후 영업일 기준 3~5일 내에 승인 여부를 이메일로 안내드립니다."),
        FAQ(category="계정", sort_order=2,
            question="비밀번호를 잊어버렸어요. 어떻게 재설정하나요?",
            answer="로그인 화면에서 '비밀번호 찾기'를 클릭하고 가입 이메일을 입력하세요. "
                   "재설정 링크가 이메일로 발송됩니다. 이메일이 오지 않는다면 스팸 폴더도 확인해 주세요."),
    ]
 
    # embedding_text 자동 생성 (RAG 검색용)
    for faq in initial_faqs:
        faq.embedding_text = f"{faq.question} {faq.answer}"
 
    db.add_all(initial_faqs)
    db.commit()
    print(f"FAQ {len(initial_faqs)}건 시드 완료.")
 

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



