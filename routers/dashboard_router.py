"""
dashboard_router.py
FastAPI 라우터 — 멘토/멘티 대시보드 API
사용법: main.py에 app.include_router(dashboard_router.router) 추가
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, date
from typing import Optional

# 기존 프로젝트의 DB/모델 import 경로에 맞게 수정하세요
from database import get_db, SessionLocal
from models import User, Mentor, Booking, ChatSession, Review

# ── SavedMentor 모델 (database.py / models.py에 추가하세요) ──────────
# 아래 import 대신 직접 models.py에 붙여넣기 해도 됩니다
try:
    from models import SavedMentor
except ImportError:
    # 모델이 아직 없으면 여기서 임시 정의 (models.py에 정식 추가 권장)
    from sqlalchemy import UniqueConstraint
    from database import Base
    from sqlalchemy import Column, Integer, DateTime
    from sqlalchemy import func as sqlfunc

    class SavedMentor(Base):
        __tablename__ = "saved_mentors"
        __table_args__ = (
            UniqueConstraint('user_id', 'mentor_id', name='uq_saved_mentor'),
            {'schema': 'public'}
        )
        id        = Column(Integer, primary_key=True, index=True)
        user_id   = Column(Integer, nullable=False, index=True)   # 찜한 멘티 user_id
        mentor_id = Column(Integer, nullable=False, index=True)   # 찜 당한 mentor.id
        created_at = Column(DateTime, server_default=sqlfunc.now())

    # 테이블 자동 생성 (최초 1회)
    from database import engine
    Base.metadata.create_all(bind=engine)


router = APIRouter(prefix="/api", tags=["dashboard"])


# ════════════════════════════════════════════════════════════════
#  멘토 대시보드  GET /api/mentor/dashboard/{user_id}
# ════════════════════════════════════════════════════════════════
@router.get("/mentor/dashboard/{user_id}")
def mentor_dashboard(user_id: int, db: Session = Depends(get_db)):
    """
    해당 user_id가 멘토로 등록된 경우에만 데이터를 반환합니다.
    멘토가 아니면 404를 반환해 프론트가 isMentor=false로 처리하게 합니다.
    """

    # 1) 멘토 존재 확인
    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
    if not mentor:
        raise HTTPException(status_code=404, detail="멘토 등록 정보가 없습니다.")

    user = db.query(User).filter(User.id == user_id).first()

    today = date.today()
    this_month_start = today.replace(day=1)

    # ── 통계 계산 ─────────────────────────────────────────────────

    # 이번 달 완료된 예약 수익
    # Booking에 price 컬럼이 없으므로 Mentor.price 파싱 또는 건당 고정값 사용
    # 여기선 건당 mentor.price를 숫자로 파싱 시도, 실패 시 0
    def parse_price(price_str: Optional[str]) -> int:
        if not price_str:
            return 0
        import re
        nums = re.sub(r"[^\d]", "", price_str)
        return int(nums) if nums else 0

    price_per_session = parse_price(mentor.price)

    monthly_bookings_count = (
        db.query(func.count(Booking.id))
        .filter(
            Booking.mentor_id == mentor.id,
            Booking.status == "PAID",
            Booking.booking_date >= this_month_start,
        )
        .scalar() or 0
    )
    monthly_earnings = monthly_bookings_count * price_per_session

    # 평균 평점
    avg_rating_row = (
        db.query(func.avg(Review.rating))
        .filter(Review.mentor_id == mentor.id)
        .scalar()
    )
    average_rating = round(float(avg_rating_row), 1) if avg_rating_row else 0.0

    # 총 멘토링 시간 (chat_sessions duration_sec 합산)
    total_sec = (
        db.query(func.sum(ChatSession.duration_sec))
        .filter(ChatSession.mentor_id == mentor.id)
        .scalar() or 0
    )
    mentoring_hours = round(total_sec / 3600, 1)

    # 재예약률: 동일 user_id가 2회 이상 예약한 비율
    total_users = (
        db.query(func.count(func.distinct(Booking.user_id)))
        .filter(Booking.mentor_id == mentor.id)
        .scalar() or 0
    )
    rebooking_users = (
        db.query(func.count(Booking.user_id))
        .filter(Booking.mentor_id == mentor.id)
        .group_by(Booking.user_id)
        .having(func.count(Booking.id) >= 2)
        .count()
    )
    rebooking_rate = round((rebooking_users / total_users * 100), 1) if total_users else 0.0

    # ── 예정된 멘토링 ──────────────────────────────────────────────
    upcoming_rows = (
        db.query(Booking, User)
        .join(User, User.id == Booking.user_id)
        .filter(
            Booking.mentor_id == mentor.id,
            Booking.booking_date >= today,
            Booking.status == "PAID",
        )
        .order_by(Booking.booking_date, Booking.booking_time)
        .limit(10)
        .all()
    )
    upcoming_chats = [
        {
            "id": b.id,
            "mentee_name": u.name,
            "scheduled_time": f"{b.booking_date} {b.booking_time}",
            "status": "예정",
        }
        for b, u in upcoming_rows
    ]

    # ── 최근 리뷰 ─────────────────────────────────────────────────
    review_rows = (
        db.query(Review, User)
        .join(User, User.id == Review.user_id)
        .filter(Review.mentor_id == mentor.id)
        .order_by(Review.created_at.desc())
        .limit(5)
        .all()
    )
    recent_reviews = [
        {
            "mentee_name": u.name,
            "rating": r.rating,
            "content": r.review,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r, u in review_rows
    ]

    return {
        "stats": {
            "name": user.name if user else mentor.name,
            "monthly_earnings": monthly_earnings,
            "average_rating": average_rating,
            "mentoring_hours": mentoring_hours,
            "rebooking_rate": rebooking_rate,
        },
        "upcoming_chats": upcoming_chats,
        "recent_reviews": recent_reviews,
    }


# ════════════════════════════════════════════════════════════════
#  멘티 대시보드  GET /api/mentee/dashboard/{user_id}
# ════════════════════════════════════════════════════════════════
@router.get("/mentee/dashboard/{user_id}")
def mentee_dashboard(user_id: int, db: Session = Depends(get_db)):

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다.")

    today = date.today()

    # ── 통계 계산 ─────────────────────────────────────────────────

    # 참여한 커피챗 수 (완료된 예약)
    total_chats = (
        db.query(func.count(Booking.id))
        .filter(Booking.user_id == user_id, Booking.status == "PAID")
        .scalar() or 0
    )

    # 총 학습 시간 (chat_sessions 기준)
    total_sec = (
        db.query(func.sum(ChatSession.duration_sec))
        .filter(ChatSession.user_id == user_id)
        .scalar() or 0
    )
    learning_hours = round(total_sec / 3600, 1)

    # 만난 멘토 수 (중복 제거)
    mentor_count = (
        db.query(func.count(func.distinct(Booking.mentor_id)))
        .filter(Booking.user_id == user_id)
        .scalar() or 0
    )

    # 관심(찜) 멘토 수
    saved_count = (
        db.query(func.count(SavedMentor.id))
        .filter(SavedMentor.user_id == user_id)
        .scalar() or 0
    )

    # ── 다가오는 예약 ──────────────────────────────────────────────
    upcoming_rows = (
        db.query(Booking, Mentor)
        .join(Mentor, Mentor.id == Booking.mentor_id)
        .filter(
            Booking.user_id == user_id,
            Booking.booking_date >= today,
            Booking.status == "PAID",
        )
        .order_by(Booking.booking_date, Booking.booking_time)
        .limit(10)
        .all()
    )
    upcoming_bookings = [
        {
            "id": b.id,
            "mentor_name": m.name,
            "scheduled_time": f"{b.booking_date} {b.booking_time}",
            "status": "예정",
        }
        for b, m in upcoming_rows
    ]

    # ── 최근 만난 멘토 이력 ────────────────────────────────────────
    # 완료된 예약 기준, 가장 최근 순으로 멘토 중복 제거
    history_rows = (
        db.query(Booking, Mentor, Review)
        .join(Mentor, Mentor.id == Booking.mentor_id)
        .outerjoin(
            Review,
            (Review.booking_id == Booking.id) & (Review.user_id == user_id)
        )
        .filter(
            Booking.user_id == user_id,
            Booking.booking_date < today,   # 완료된 것만
            Booking.status == "PAID",
        )
        .order_by(Booking.booking_date.desc())
        .limit(20)
        .all()
    )

    # 멘토 중복 제거 (최근 1건만 유지)
    seen_mentor_ids = set()
    mentor_history = []
    for b, m, r in history_rows:
        if m.id in seen_mentor_ids:
            continue
        seen_mentor_ids.add(m.id)
        mentor_history.append({
            "mentor_id": m.id,
            "mentor_name": m.name,
            "topic": m.mentoring_topics.split("\n")[0] if m.mentoring_topics else None,
            "date": b.booking_date.isoformat() if b.booking_date else None,
            "my_rating": r.rating if r else None,
        })
        if len(mentor_history) >= 5:
            break

    return {
        "stats": {
            "name": user.name,
            "total_chats": total_chats,
            "learning_hours": learning_hours,
            "mentor_count": mentor_count,
            "saved_mentors": saved_count,
        },
        "upcoming_bookings": upcoming_bookings,
        "mentor_history": mentor_history,
    }


# ════════════════════════════════════════════════════════════════
#  멘토 찜 토글  POST /api/mentee/save-mentor
# ════════════════════════════════════════════════════════════════
@router.post("/mentee/save-mentor")
def toggle_save_mentor(
    user_id: int,
    mentor_id: int,
    db: Session = Depends(get_db),
):
    """찜 추가/취소 토글. 반환: { saved: bool }"""
    existing = (
        db.query(SavedMentor)
        .filter(SavedMentor.user_id == user_id, SavedMentor.mentor_id == mentor_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return {"saved": False}
    else:
        db.add(SavedMentor(user_id=user_id, mentor_id=mentor_id))
        db.commit()
        return {"saved": True}