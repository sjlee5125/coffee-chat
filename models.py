import enum
import socket
from datetime import datetime
from sqlalchemy import (
    create_engine, JSON, Column, Integer, String, Boolean, Text,
    Enum, DateTime, ForeignKey, Date, func, UniqueConstraint, Float
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
from database import Base


# ─── 1. 데이터베이스 연결 설정 ───
hostname = socket.gethostname()
if hostname == "coffeechat":
    SQLALCHEMY_DATABASE_URL = "postgresql://postgres:soldesk0526@localhost:5432/postgres"
else:
    SQLALCHEMY_DATABASE_URL = "postgresql://postgres:soldesk0526@48.211.169.52:5432/postgres"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pdf_url = Column(String, nullable=True)
# ─── 2. 공통 데이터 모델 정의 ───

class UserRole(enum.Enum):
    MENTOR = "mentor"
    MENTEE = "mentee"
    ADMIN  = "admin"


class User(Base):
    __tablename__ = "users"
    __table_args__ = {'schema': 'public'}

    id                 = Column(Integer, primary_key=True, index=True)
    email              = Column(String(255), unique=True, nullable=False, index=True)
    name               = Column(String(100), nullable=False)
    password_hash      = Column(String(255), nullable=True)
    role               = Column(Enum(UserRole), nullable=True, default=UserRole.MENTEE)
    provider           = Column(String(50), default="local")
    provider_id        = Column(String(255), unique=True, nullable=True)
    bio                = Column(Text, nullable=True)
    mbti               = Column(String(4), nullable=True)
    hashtags           = Column(String(255), nullable=True)
    experience         = Column(Text, nullable=True)
    portfolio_url      = Column(Text, nullable=True)
    portfolio_file_path= Column(Text, nullable=True)
    help_provide       = Column(Text, nullable=True)
    help_receive       = Column(Text, nullable=True)
    profile_image      = Column(Text, nullable=True)
    phone_number       = Column(String(20), nullable=True)
    created_at         = Column(DateTime, server_default=func.now())

    mentor_profile = relationship("Mentor", backref="user_ref", uselist=False)


class Mentor(Base):
    __tablename__ = "mentors"
    __table_args__ = {'schema': 'public'}

    id                 = Column(Integer, primary_key=True, index=True)
    # ✅ user_id 중복 선언 제거 — ForeignKey 버전만 유지
    user_id            = Column(Integer, ForeignKey("public.users.id"), unique=True, nullable=False)
    name               = Column(String(100), nullable=False)
    price              = Column(String(50), default="10,000 원")
    job_title          = Column(String(100), nullable=True)
    career_history     = Column(Text, nullable=True)
    mentor_intro       = Column(Text, nullable=True)
    mentoring_topics   = Column(Text, nullable=True)
    detailed_experience= Column(Text, nullable=True)
    status             = Column(String(50), nullable=True)
    main_category      = Column(String(100), nullable=True)
    sub_category       = Column(String(100), nullable=True)
    views              = Column(Integer, default=0, nullable=False)
    # ✅ 노쇼/패널티 컬럼
    noshow_count       = Column(Integer, default=0, nullable=False)
    penalty_end_date   = Column(DateTime, nullable=True)
    is_banned          = Column(Boolean, default=False, nullable=False)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = {'schema': 'public'}

    id               = Column(Integer, primary_key=True, index=True)
    mentor_id        = Column(Integer, ForeignKey("public.mentors.id"))
    user_id          = Column(Integer, ForeignKey("public.users.id"))
    booking_date     = Column(Date)
    booking_time     = Column(String)
    questions        = Column(String)
    status           = Column(String, default="PAID")
    created_at       = Column(DateTime, server_default=func.now())
    penalty_applied  = Column(Boolean, default=False, nullable=False)
    cancelled_at     = Column(DateTime, nullable=True)
    cancelled_by     = Column(String(10), nullable=True)
    # ✅ 입장 여부 플래그
    is_mentor_entered = Column(Boolean, default=False, nullable=False)
    is_mentee_entered = Column(Boolean, default=False, nullable=False)
    # ✅ 노쇼 마킹 플래그 (penalty_service.py에서 사용)
    mentor_noshow    = Column(Boolean, default=False, nullable=False)
    mentee_noshow    = Column(Boolean, default=False, nullable=False)


class MentorAvailability(Base):
    __tablename__ = "mentor_availability"
    __table_args__ = (
        UniqueConstraint('mentor_id', 'date', 'time', name='uq_mentor_date_time'),
        {'schema': 'public'}
    )

    id         = Column(Integer, primary_key=True, index=True)
    mentor_id  = Column(Integer, nullable=False, index=True)
    date       = Column(Date, nullable=False)
    time       = Column(String(5), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {'schema': 'public'}

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("public.users.id", ondelete="CASCADE"))
    message    = Column(String(255))
    is_read    = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = {'schema': 'public'}

    id                   = Column(Integer, primary_key=True, index=True)
    booking_id           = Column(Integer, nullable=True)
    mentor_id            = Column(Integer, nullable=True)
    user_id              = Column(Integer, nullable=True)
    started_at           = Column(DateTime, nullable=True)
    ended_at             = Column(DateTime, nullable=True)
    duration_sec         = Column(Integer, nullable=True)
    stt_text             = Column(Text, nullable=True)
    ai_summary           = Column(Text, nullable=True)
    status               = Column(String(20), default="READY")
    created_at           = Column(DateTime, server_default=func.now())
    recommended_questions= Column(JSON, nullable=True)


class CoffeeChatReport(Base):
    __tablename__ = "coffee_chat_reports"
    __table_args__ = {'schema': 'public'}

    id             = Column(Integer, primary_key=True, index=True)
    chatsession_id = Column(Integer, ForeignKey("public.chat_sessions.id", ondelete="CASCADE"), unique=True, nullable=False)
    mentor_id      = Column(Integer, ForeignKey("public.mentors.id"), nullable=False)
    mentee_id      = Column(Integer, ForeignKey("public.users.id"), nullable=False)
    stt_masked     = Column(Text, nullable=True)
    summary        = Column(Text, nullable=True)
    ai_advice      = Column(Text, nullable=True)
    created_at     = Column(DateTime, server_default=func.now())
    updated_at     = Column(DateTime, server_default=func.now(), onupdate=func.now())
    masking_map    = Column(JSON, nullable=True)


class SavedMentor(Base):
    __tablename__ = "saved_mentors"
    __table_args__ = (
        UniqueConstraint('user_id', 'mentor_id', name='uq_saved_mentor'),
        {'schema': 'public'}
    )

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, nullable=False, index=True)
    mentor_id  = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = {'schema': 'public'}

    id         = Column(Integer, primary_key=True, index=True)
    title      = Column(String(255), nullable=False)
    content    = Column(Text, nullable=False)
    author_id  = Column(Integer, ForeignKey("public.users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = {'schema': 'public'}

    id         = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, nullable=False)
    mentor_id  = Column(Integer, nullable=False)
    user_id    = Column(Integer, nullable=False)
    rating     = Column(Integer, nullable=False)
    review     = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ─── FAQ 테이블 ───────────────────────────────────────────────────────────────
class FAQ(Base):
    __tablename__ = "faqs"
    __table_args__ = {'schema': 'public'}

    id             = Column(Integer, primary_key=True, index=True)
    category       = Column(String(50), nullable=False, index=True)
    question       = Column(Text, nullable=False)
    answer         = Column(Text, nullable=False)
    embedding_text = Column(Text, nullable=True)       # RAG용 원본 텍스트
    # ✅ pgvector용 embedding 컬럼 — DB에 vector 타입으로 존재해야 함
    # ALTER TABLE public.faqs ADD COLUMN IF NOT EXISTS embedding vector(3072);
    # SQLAlchemy에서는 Text로 선언 후 raw SQL로 캐스팅해서 사용
    is_active      = Column(Boolean, default=True, nullable=False)
    sort_order     = Column(Integer, default=0, nullable=False)
    created_at     = Column(DateTime, server_default=func.now())
    updated_at     = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ─── 1:1 문의 테이블 ──────────────────────────────────────────────────────────
class InquiryStatus(enum.Enum):
    PENDING   = "pending"
    IN_REVIEW = "in_review"
    ANSWERED  = "answered"
    CLOSED    = "closed"


class Inquiry(Base):
    __tablename__ = "inquiries"
    __table_args__ = {'schema': 'public'}

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True, index=True)
    category    = Column(String(50), nullable=False)
    title       = Column(String(200), nullable=False)
    body        = Column(Text, nullable=False)
    email       = Column(String(255), nullable=False)
    # ✅ 들여쓰기 오류 수정 + values_callable로 소문자 value 저장
    status      = Column(
        Enum(InquiryStatus, values_callable=lambda x: [e.value for e in x]),
        default=InquiryStatus.PENDING,
        nullable=False,
        index=True,
    )
    answer      = Column(Text, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    answered_by = Column(Integer, ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    admin_note  = Column(Text, nullable=True)
    created_at  = Column(DateTime, server_default=func.now())
    updated_at  = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ─── FAQ 초기 데이터 시드 함수 ───────────────────────────────────────────────
def seed_faqs(db):
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

    for faq in initial_faqs:
        faq.embedding_text = f"{faq.question} {faq.answer}"

    db.add_all(initial_faqs)
    db.commit()
    print(f"FAQ {len(initial_faqs)}건 시드 완료.")


# ─── DB 헬퍼 ─────────────────────────────────────────────────────────────────
def create_tables():
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