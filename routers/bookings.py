import os
from pydantic import BaseModel
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import User, Mentor, Booking, MentorAvailability, Notification, get_db, ChatSession, Review
from routers.notifications import manager 
from datetime import datetime, timedelta
import requests

router = APIRouter(
    prefix="/api/booking",
    tags=["Bookings"]
)

class BookingCreateRequest(BaseModel):
    mentorId: int
    userId: int
    date: date
    time: str
    questions: str

class PaymentVerifyRequest(BaseModel):
    paymentId: str
    orderId: str
    amount: int

class ReviewCreateRequest(BaseModel):
    booking_id: int
    user_id: int
    mentor_id: int
    rating: int
    review: str


# ==========================================================
# 공통 유틸: booking_time 문자열 → datetime 안전 파싱
# ==========================================================
def _parse_booking_datetime(booking_date, booking_time) -> datetime:
    """
    booking_time이 "15:00", "15:00:00", "3:00 PM" 등 어떤 포맷이어도
    안전하게 datetime으로 변환합니다.
    파싱 실패 시 내일 시각을 반환 → upcoming으로 처리됩니다.
    """
    try:
        date_str = str(booking_date).strip()
        time_str = str(booking_time).strip()

        # HH:MM:SS → HH:MM
        if len(time_str) > 5 and ':' in time_str:
            time_str = time_str[:5]

        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except Exception as e:
        print(f"[시간 파싱 실패] {booking_date} {booking_time}: {e}")
        return datetime.now() + timedelta(days=1)  # 파싱 실패 → 내일로 → upcoming


# ==========================================================
# 1. 커피챗 예약 생성
# ==========================================================
@router.post("/create")
async def create_booking(request: BookingCreateRequest, db: Session = Depends(get_db)):
    print(f" [예약 생성 요청] mentor_id={request.mentorId}, user_id={request.userId}")

    mentor = db.query(Mentor).filter(Mentor.id == request.mentorId).first()
    if not mentor:
        raise HTTPException(status_code=404, detail="존재하지 않는 멘토입니다.")

    user = db.query(User).filter(User.id == request.userId).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 예약자(유저) 회원입니다.")

    existing = db.query(Booking).filter(
        Booking.mentor_id == mentor.id,
        Booking.booking_date == request.date,
        Booking.booking_time == request.time,
        Booking.status == "PAID"
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="이미 예약이 완료된 시간대입니다.")

    booking = Booking(
        mentor_id=mentor.id,
        user_id=user.id,
        booking_date=request.date,
        booking_time=request.time,
        questions=request.questions,
        status="PAID"
    )
    db.add(booking)

    db.query(MentorAvailability).filter(
        MentorAvailability.mentor_id == mentor.id,
        MentorAvailability.date == request.date,
        MentorAvailability.time == request.time,
    ).delete()

    db.commit()
    db.refresh(booking)
    print(f" [예약 생성 성공] Booking ID: {booking.id}")

    try:
        target_user_id = mentor.user_id
        new_notif = Notification(
            user_id=target_user_id,
            message=f"🎉 {user.name}님으로부터 새로운 커피챗 예약 요청이 도착했습니다!",
            is_read=False
        )
        db.add(new_notif)
        db.commit()
        db.refresh(new_notif)

        await manager.send_personal_message({
            "id": new_notif.id,
            "message": new_notif.message,
            "is_read": False,
            "created_at": new_notif.created_at.isoformat() if new_notif.created_at else None,
            "type": "NEW_BOOKING_REQUEST"
        }, target_user_id)
    except Exception as ws_err:
        print(f"❌ [알림 전송 실패]: {str(ws_err)}")

    return {"message": "예약이 완료되었습니다.", "booking_id": booking.id}


# ==========================================================
# 2. 예약 확정
# ==========================================================
@router.post("/confirm/{booking_id}")
async def confirm_booking(booking_id: int, db: Session = Depends(get_db)):
    print(f" [예약 확정 요청] Booking ID: {booking_id}")

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 내역을 찾을 수 없습니다.")

    booking.status = "CONFIRMED"

    existing_session = db.query(ChatSession).filter(ChatSession.booking_id == booking_id).first()
    if not existing_session:
        db.add(ChatSession(
            booking_id=booking.id,
            mentor_id=booking.mentor_id,
            user_id=booking.user_id,
            status="READY"
        ))

    db.commit()
    print(f" [예약 확정 완료] Booking ID: {booking_id}")

    try:
        new_notif = Notification(
            user_id=booking.user_id,
            message="🎉 멘토님이 커피챗 예약을 최종 확정했습니다!",
            is_read=False
        )
        db.add(new_notif)
        db.commit()
        db.refresh(new_notif)

        await manager.send_personal_message({
            "id": new_notif.id,
            "message": new_notif.message,
            "is_read": False,
            "created_at": new_notif.created_at.isoformat() if new_notif.created_at else None,
            "type": "BOOKING_CONFIRMED",
            "booking_id": booking_id
        }, booking.user_id)
    except Exception as ws_err:
        print(f"❌ [알림 전송 실패]: {str(ws_err)}")

    return {"message": "커피챗 예약이 최종 확정되었습니다."}


# ==========================================================
# 3. 예약 거절
# ==========================================================
@router.post("/reject/{booking_id}")
async def reject_booking(booking_id: int, db: Session = Depends(get_db)):
    print(f" [예약 거절 요청] Booking ID: {booking_id}")

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 내역을 찾을 수 없습니다.")

    booking.status = "REJECTED"
    db.commit()
    print(f" [예약 거절 완료] Booking ID: {booking_id}")

    try:
        new_notif = Notification(
            user_id=booking.user_id,
            message="😢 아쉽게도 멘토님의 일정상 커피챗 예약이 거절되었습니다.",
            is_read=False
        )
        db.add(new_notif)
        db.commit()
        db.refresh(new_notif)

        await manager.send_personal_message({
            "id": new_notif.id,
            "message": new_notif.message,
            "is_read": False,
            "created_at": new_notif.created_at.isoformat() if new_notif.created_at else None,
            "type": "BOOKING_REJECTED",
            "booking_id": booking_id
        }, booking.user_id)
    except Exception as ws_err:
        print(f"❌ [알림 전송 실패]: {str(ws_err)}")

    return {"message": "커피챗 예약이 거절되었습니다."}


# ==========================================================
# 4. 신청받은 내역 (멘토용) — BookingHistory.jsx 신청받은 탭
# ==========================================================
@router.get("/mentor/{user_id}")
def get_mentor_bookings(user_id: int, db: Session = Depends(get_db)):
    """
    프론트는 로그인한 유저의 user_id를 보냄 → Mentor.user_id로 검색
    PAID(대기) 상태만 노출 — 확정/거절된 건 이미 처리됨
    """
    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
    if not mentor:
        return []

    bookings = db.query(Booking).filter(
        Booking.mentor_id == mentor.id,
        Booking.status == "PAID"   # 수락 대기 중인 것만
    ).order_by(Booking.created_at.desc()).all()

    result = []
    for b in bookings:
        mentee = db.query(User).filter(User.id == b.user_id).first()
        result.append({
            "booking_id": b.id,
            "partner_name": mentee.name if mentee else "익명 크루",
            "partner_image": mentee.profile_image if mentee and hasattr(mentee, 'profile_image') else None,
            "mentee_name": mentee.name if mentee else "익명 크루",
            "mentee_image": mentee.profile_image if mentee and hasattr(mentee, 'profile_image') else None,
            "booking_date": str(b.booking_date) if b.booking_date else "",
            "booking_time": str(b.booking_time) if b.booking_time else "",
            "candidate_times": f"{b.booking_date} {b.booking_time}",
            "questions": b.questions,
            "status": b.status
        })
    return result


# ==========================================================
# 5. 내가 신청한 내역 (멘티용) — BookingHistory.jsx 신청한 탭
# ==========================================================
@router.get("/mentee/{user_id}")
def get_mentee_bookings(user_id: int, db: Session = Depends(get_db)):
    bookings = db.query(Booking).filter(Booking.user_id == user_id) \
        .order_by(Booking.created_at.desc()).all()

    result = []
    for b in bookings:
        mentor = db.query(Mentor).filter(Mentor.id == b.mentor_id).first()
        mentor_user = db.query(User).filter(User.id == mentor.user_id).first() if mentor else None
        has_review = db.query(Review).filter(Review.booking_id == b.id).first() is not None

        result.append({
            "booking_id": b.id,
            "mentor_id": b.mentor_id,
            "has_review": has_review,
            "partner_name": mentor.name if mentor else "알 수 없는 멘토",
            "partner_image": mentor_user.profile_image if mentor_user and hasattr(mentor_user, 'profile_image') else None,
            "booking_date": str(b.booking_date) if b.booking_date else "",
            "booking_time": str(b.booking_time) if b.booking_time else "",
            "candidate_times": f"{b.booking_date} {b.booking_time}",
            "questions": b.questions,
            "status": b.status,
            "created_at": str(b.created_at) if b.created_at else ""
        })

    return result


# ==========================================================
# 6. 예약 상세 조회
# ==========================================================
@router.get("/detail/{booking_id}")
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 정보를 찾을 수 없습니다.")

    mentor = db.query(Mentor).filter(Mentor.id == booking.mentor_id).first()
    mentee_user = db.query(User).filter(User.id == booking.user_id).first()

    return {
        "id": booking.id,
        "booking_date": str(booking.booking_date),
        "booking_time": booking.booking_time,
        "questions": booking.questions,
        "status": booking.status,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
        "mentor_id": booking.mentor_id,
        "mentor_user_id": mentor.user_id if mentor else None,
        "user_id": booking.user_id,
        "mentor_name": mentor.name if mentor else "멘토",
        "user_name": mentee_user.name if mentee_user else "멘티"
    }


# ==========================================================
# 7. 결제 검증
# ==========================================================
@router.post("/payment/verify")
def verify_payment(data: PaymentVerifyRequest):
    portone_secret = os.getenv("PORTONE_API_SECRET")
    if not portone_secret:
        raise HTTPException(status_code=500, detail="포트원 API Secret이 설정되지 않았습니다.")

    res = requests.get(
        f"https://api.portone.io/payments/{data.paymentId}",
        headers={"Authorization": f"PortOne {portone_secret}"}
    )

    if res.status_code != 200:
        raise HTTPException(status_code=400, detail=f"포트원 결제 조회 실패: {res.text}")

    payment = res.json()

    if payment.get("status") != "PAID":
        raise HTTPException(status_code=400, detail=f"결제가 완료되지 않았습니다. 현재 상태: {payment.get('status')}")

    paid_amount = payment.get("amount", {}).get("total")
    if paid_amount != data.amount:
        raise HTTPException(status_code=400, detail=f"결제 금액 불일치. 결제: {paid_amount}, 요청: {data.amount}")

    return {"success": True, "paymentId": data.paymentId, "orderId": data.orderId}


# ==========================================================
# 8. CoffeeChats.jsx 전용 — CONFIRMED 예약 + tab_status 계산
# ==========================================================
@router.get("/{user_id}")
def get_bookings(user_id: int, db: Session = Depends(get_db)):
    print(f" [CoffeeChats 조회] User ID: {user_id}")

    mentor = db.query(Mentor).filter(
        (Mentor.user_id == user_id) | (Mentor.id == user_id)
    ).first()
    mentor_id = mentor.id if mentor else -1

    bookings = db.query(Booking).filter(
        Booking.status == "CONFIRMED",
        (Booking.user_id == user_id) | (Booking.mentor_id == mentor_id)
    ).order_by(Booking.booking_date.asc()).all()

    now = datetime.now()
    result = []

    for b in bookings:
        booking_datetime = _parse_booking_datetime(b.booking_date, b.booking_time)

        # ── tab_status 계산 ──────────────────────────────
        # 1순위: ChatSession 상태가 명시적으로 COMPLETED/ONGOING이면 그걸 따름
        chat_session = db.query(ChatSession).filter(ChatSession.booking_id == b.id).first()

        if chat_session and chat_session.status == "COMPLETED":
            tab_status = "completed"
        elif chat_session and chat_session.status == "ONGOING":
            tab_status = "ongoing"
        else:
            # 2순위: 시간 기준으로 계산
            diff_min = (booking_datetime - now).total_seconds() / 60

            if diff_min > 5:
                # 아직 5분 이상 남음 → 예정
                tab_status = "upcoming"
            elif -30 <= diff_min <= 5:
                # 시작 5분 전 ~ 시작 후 30분 이내 → 진행중
                tab_status = "ongoing"
            else:
                # 30분 이상 지남 → 종료
                tab_status = "completed"

        print(f" [tab_status] booking_id={b.id} date={b.booking_date} time={b.booking_time} "
              f"booking_dt={booking_datetime} now={now} diff_min={round((booking_datetime - now).total_seconds()/60, 1)} "
              f"→ {tab_status}")

        # ── 상대방 이름 ──────────────────────────────────
        if b.user_id == user_id:
            target_mentor = db.query(Mentor).filter(Mentor.id == b.mentor_id).first()
            partner_name = target_mentor.name if target_mentor else f"멘토 #{b.mentor_id}"
        else:
            target_mentee = db.query(User).filter(User.id == b.user_id).first()
            partner_name = target_mentee.name if target_mentee else "크루(예약자)"

        has_review = db.query(Review).filter(Review.booking_id == b.id).first() is not None

        result.append({
            "id": b.id,
            "mentor_id": b.mentor_id,
            "mentor_name": partner_name,
            "user_id": b.user_id,
            "booking_date": str(b.booking_date),
            "booking_time": str(b.booking_time)[:5],  # HH:MM 만 전달
            "questions": b.questions,
            "status": b.status,
            "tab_status": tab_status,
            "has_review": has_review,
            "created_at": str(b.created_at)
        })

    return result


# ==========================================================
# 9. 리뷰 작성
# ==========================================================
@router.post("/review/create")
def create_review(request: ReviewCreateRequest, db: Session = Depends(get_db)):
    existing_review = db.query(Review).filter(Review.booking_id == request.booking_id).first()
    if existing_review:
        raise HTTPException(status_code=400, detail="이미 작성된 리뷰가 있습니다.")

    review = Review(
        booking_id=request.booking_id,
        user_id=request.user_id,
        mentor_id=request.mentor_id,
        rating=request.rating,
        review=request.review
    )
    db.add(review)

    mentor = db.query(Mentor).filter(Mentor.id == request.mentor_id).first()
    if mentor:
        reviews = db.query(Review).filter(Review.mentor_id == request.mentor_id).all()
        total = sum(r.rating for r in reviews) + request.rating
        count = len(reviews) + 1
        mentor.avg_rating = total / count

    db.commit()
    return {"message": "리뷰가 저장됐어요!"}


# ==========================================================
# 10. 멘토 리뷰 조회
# ==========================================================
@router.get("/reviews/{mentor_id}")
def get_mentor_reviews(mentor_id: int, db: Session = Depends(get_db)):
    reviews = db.query(Review).filter(Review.mentor_id == mentor_id).all()

    result = []
    for r in reviews:
        user = db.query(User).filter(User.id == r.user_id).first()
        result.append({
            "id": r.id,
            "booking_id": r.booking_id,
            "user_id": r.user_id,
            "author": user.name if user else "익명",
            "author_image": user.profile_image if user else "",
            "rating": r.rating,
            "comment": r.review,
            "created_at": str(r.created_at)
        })

    return result


# ==========================================================
# 11. 유사 멘토 추천
# ==========================================================
@router.get("/recommend/{booking_id}")
def get_recommended_mentors(booking_id: int, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return []

    current_mentor = db.query(Mentor).filter(Mentor.id == booking.mentor_id).first()
    if not current_mentor:
        return []

    similar_mentors = db.query(Mentor).filter(
        Mentor.job_title == current_mentor.job_title,
        Mentor.id != current_mentor.id
    ).limit(3).all()

    if len(similar_mentors) < 3:
        from sqlalchemy import func
        similar_mentors = db.query(Mentor).filter(
            Mentor.id != current_mentor.id
        ).order_by(func.random()).limit(3).all()

    result = []
    for m in similar_mentors:
        user = db.query(User).filter(User.id == m.user_id).first()
        result.append({
            "mentor_id": m.user_id,
            "name": m.name,
            "job_title": m.job_title or "직무 미정",
            "profile_image": user.profile_image if user else "",
            "avg_rating": getattr(m, 'avg_rating', 0) or 0
        })

    return result