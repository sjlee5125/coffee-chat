"""
dashboard_router.py
FastAPI 라우터 — 멘토/멘티 대시보드 API
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date

from database import get_db
from models import User, Mentor, Booking, ChatSession, Review

router = APIRouter(prefix="/api", tags=["dashboard"])

# ════════════════════════════════════════════════════════════════
#  멘토 대시보드
# ════════════════════════════════════════════════════════════════
@router.get("/mentor/dashboard/{user_id}")
def mentor_dashboard(user_id: int, db: Session = Depends(get_db)):
    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
    if not mentor:
        raise HTTPException(status_code=404, detail="멘토 등록 정보가 없습니다.")

    user = db.query(User).filter(User.id == user_id).first()
    today = date.today()
    this_month_start = today.replace(day=1)

    FIXED_PRICE = 15000
    monthly_bookings_count = (
        db.query(func.count(Booking.id))
        .filter(
            Booking.mentor_id == mentor.id,
            Booking.status == "PAID",
            Booking.booking_date >= this_month_start,
        )
        .scalar() or 0
    )
    monthly_earnings = monthly_bookings_count * FIXED_PRICE

    avg_rating_row = db.query(func.avg(Review.rating)).filter(Review.mentor_id == mentor.id).scalar()
    average_rating = round(float(avg_rating_row), 1) if avg_rating_row else 0.0

    total_seconds = (
        db.query(
            func.sum(
                func.extract('epoch', ChatSession.ended_at) - func.extract('epoch', ChatSession.started_at)
            )
        )
        .filter(ChatSession.mentor_id == mentor.id)
        .scalar() or 0
    )
    mentoring_hours = round(total_seconds / 3600, 1)

    total_users = db.query(func.count(func.distinct(Booking.user_id))).filter(Booking.mentor_id == mentor.id).scalar() or 0
    rebooking_users = (
        db.query(Booking.user_id)
        .filter(Booking.mentor_id == mentor.id)
        .group_by(Booking.user_id)
        .having(func.count(Booking.id) >= 2)
        .count()
    )
    rebooking_rate = round((rebooking_users / total_users * 100), 1) if total_users else 0.0

    upcoming_rows = (
        db.query(Booking.id, Booking.booking_date, Booking.booking_time, Booking.status, User.name)
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
            "id": row.id,
            "mentee_name": row.name,
            "scheduled_time": f"{row.booking_date} {row.booking_time}",
            "status": row.status,
        }
        for row in upcoming_rows
    ]

    # 💡 [핵심 수정] Review 전체를 가져오지 않고, 필요한 컬럼만 콕 집어서 가져옴 (content 회피)
    review_rows = (
        db.query(User.name, Review.rating, Review.created_at)
        .select_from(Review)
        .join(User, User.id == Review.user_id)
        .filter(Review.mentor_id == mentor.id)
        .order_by(Review.created_at.desc())
        .limit(5)
        .all()
    )
    
    recent_reviews = [
        {
            "mentee_name": row.name,
            "rating": row.rating,
            "content": "", # 내용 없음
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in review_rows
    ]

    return {
        "stats": {
            "name": user.name if user else mentor.name,
            "monthly_earnings": monthly_earnings,
            "monthly_session_count": monthly_bookings_count,
            "average_rating": average_rating,
            "mentoring_hours": mentoring_hours,
            "rebooking_rate": rebooking_rate,
        },
        "upcoming_chats": upcoming_chats,
        "recent_reviews": recent_reviews,
    }


# ════════════════════════════════════════════════════════════════
#  멘티 대시보드
# ════════════════════════════════════════════════════════════════
@router.get("/mentee/dashboard/{user_id}")
def mentee_dashboard(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다.")

    today = date.today()

    total_chats = db.query(func.count(Booking.id)).filter(Booking.user_id == user_id, Booking.status == "PAID").scalar() or 0

    total_seconds = (
        db.query(
            func.sum(
                func.extract('epoch', ChatSession.ended_at) - func.extract('epoch', ChatSession.started_at)
            )
        )
        .filter(ChatSession.user_id == user_id)
        .scalar() or 0
    )
    learning_hours = round(total_seconds / 3600, 1)

    upcoming_rows = (
        db.query(Booking.id, Booking.booking_date, Booking.booking_time, Booking.status, Mentor.name)
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
            "id": row.id,
            "mentor_name": row.name,
            "scheduled_time": f"{row.booking_date} {row.booking_time}",
            "status": row.status,
        }
        for row in upcoming_rows
    ]

    # 💡 [핵심 수정] 멘티 대시보드에서도 필요한 컬럼만 가져옴
    history_rows = (
        db.query(Booking.booking_date, Mentor.id, Mentor.name, Mentor.mentoring_topics, Review.rating)
        .select_from(Booking)
        .join(Mentor, Mentor.id == Booking.mentor_id)
        .outerjoin(
            Review,
            (Review.booking_id == Booking.id) & (Review.user_id == user_id)
        )
        .filter(
            Booking.user_id == user_id,
            Booking.booking_date < today,
            Booking.status == "PAID",
        )
        .order_by(Booking.booking_date.desc())
        .limit(20)
        .all()
    )

    seen_mentor_ids = set()
    mentor_history = []
    for booking_date, m_id, m_name, m_topics, r_rating in history_rows:
        if m_id in seen_mentor_ids:
            continue
        seen_mentor_ids.add(m_id)
        mentor_history.append({
            "mentor_id": m_id,
            "mentor_name": m_name,
            "topic": m_topics.split("\n")[0] if m_topics else None,
            "date": booking_date.isoformat() if booking_date else None,
            "my_rating": r_rating,
        })
        if len(mentor_history) >= 5:
            break

    return {
        "stats": {
            "name": user.name,
            "total_chats": total_chats,
            "learning_hours": learning_hours,
        },
        "upcoming_bookings": upcoming_bookings,
        "mentor_history": mentor_history,
    }