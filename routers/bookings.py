import os
from pydantic import BaseModel
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
# bookings.py 상단 수정
from models import User, Mentor, Booking, MentorAvailability, Notification, get_db, ChatSession, Review
from routers.notifications import manager 
from datetime import datetime, timedelta
import requests

# 라우터 생성
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
# 1. 커피챗 예약 생성
# ==========================================================
@router.post("/create")
async def create_booking(request: BookingCreateRequest, db: Session = Depends(get_db)):
    """멘티의 커피챗 예약 생성 API"""
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
    print(f" [예약 생성 성공 완결] Booking ID: {booking.id} 매핑 데이터 세팅 완료")

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

        notif_data = {
            "id": new_notif.id,
            "message": new_notif.message,
            "is_read": False,
            "created_at": new_notif.created_at.isoformat() if new_notif.created_at else None,
            "type": "NEW_BOOKING_REQUEST"
        }
        await manager.send_personal_message(notif_data, target_user_id)
        
    except Exception as ws_err:
        print(f"❌ [알림 전송 실패]: {str(ws_err)}")

    return {"message": "예약이 완료되었습니다.", "booking_id": booking.id}


# ==========================================================
# 2. 예약 확정 
# ==========================================================
@router.post("/confirm/{booking_id}")
async def confirm_booking(booking_id: int, db: Session = Depends(get_db)):
    """예약 확정 시 멘티에게 실시간 알림 전송 및 채팅 세션 생성 API"""
    print(f" [예약 최종 수락 요청] Booking ID: {booking_id}")
    
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 내역을 찾을 수 없습니다.")
    
    booking.status = "CONFIRMED"
    
    existing_session = db.query(ChatSession).filter(ChatSession.booking_id == booking_id).first()
    if not existing_session:
        new_session = ChatSession(
            booking_id=booking.id,
            mentor_id=booking.mentor_id,
            user_id=booking.user_id,
            status="READY"
        )
        db.add(new_session)

    db.commit()
    
    try:
        new_notif = Notification(
            user_id=booking.user_id,
            message=f"🎉 멘토님이 커피챗 예약을 최종 확정했습니다!",
            is_read=False
        )
        db.add(new_notif)
        db.commit()
        db.refresh(new_notif)

        notif_data = {
            "id": new_notif.id,
            "message": new_notif.message,
            "is_read": False,
            "created_at": new_notif.created_at.isoformat() if new_notif.created_at else None,
            "type": "BOOKING_CONFIRMED",
            "booking_id": booking_id
        }
        await manager.send_personal_message(notif_data, booking.user_id)
        
    except Exception as ws_err:
        print(f"❌ [알림 전송 실패]: {str(ws_err)}")
    
    return {"message": "커피챗 예약이 최종 확정되었습니다."}

# ==========================================================
# 3. 예약 거절 
# ==========================================================
@router.post("/reject/{booking_id}")
async def reject_booking(booking_id: int, db: Session = Depends(get_db)):
    """예약 거절 시 멘티에게 실시간 알림 전송 API"""
    print(f" [예약 거절 요청] Booking ID: {booking_id}")
    
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 내역을 찾을 수 없습니다.")
    
    booking.status = "REJECTED"
    db.commit()
    
    try:
        new_notif = Notification(
            user_id=booking.user_id,
            message=f"😢 아쉽게도 멘토님의 일정상 커피챗 예약이 거절되었습니다.",
            is_read=False
        )
        db.add(new_notif)
        db.commit()
        db.refresh(new_notif)

        notif_data = {
            "id": new_notif.id,
            "message": new_notif.message,
            "is_read": False,
            "created_at": new_notif.created_at.isoformat() if new_notif.created_at else None,
            "type": "BOOKING_REJECTED",
            "booking_id": booking_id
        }
        await manager.send_personal_message(notif_data, booking.user_id)
        
    except Exception as ws_err:
        print(f"❌ [알림 전송 실패]: {str(ws_err)}")
    
    return {"message": "커피챗 예약이 거절되었습니다."}

@router.get("/mentor/{user_id}")
def get_mentor_bookings(user_id: int, db: Session = Depends(get_db)):
    """
    멘토 대시보드 (신청받은 내역)
    프론트에서 로그인한 유저의 회원 번호를 보내므로, 무조건 Mentor.user_id로 찾아야 합니다!
    """
    # 💡 1. 엉뚱한 사람 찾기 방지! (무조건 user_id로만 검색)
    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
    
    if not mentor:
        return []

    # 💡 2. PAID 필터 삭제! (이제 대기, 확정, 거절 내역 모두 뜹니다)
    bookings = db.query(Booking).filter(
        Booking.mentor_id == mentor.id
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

@router.get("/mentee/{user_id}")
def get_mentee_bookings(user_id: int, db: Session = Depends(get_db)):
    bookings = db.query(Booking).filter(Booking.user_id == user_id)\
    .order_by(Booking.created_at.desc()).all()

    result = []
    for b in bookings:
        mentor = db.query(Mentor).filter(Mentor.id == b.mentor_id).first()
        mentor_user = db.query(User).filter(User.id == mentor.user_id).first() if mentor else None
        
        has_review = db.query(Review).filter(Review.booking_id == b.id).first() is not None

        # 💡 [수정됨] 프론트엔드가 요구하는 키값으로 정확하게 복구! (정의되지 않은 변수 삭제)
        result.append({
            "booking_id": b.id,  # 프론트가 booking_id로 라우팅합니다.
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

@router.post("/payment/verify")
def verify_payment(data: PaymentVerifyRequest):
    portone_secret = os.getenv("PORTONE_API_SECRET")

    if not portone_secret:
        raise HTTPException(status_code=500, detail="포트원 API Secret이 설정되지 않았습니다.")

    res = requests.get(
        f"https://api.portone.io/payments/{data.paymentId}",
        headers={
            "Authorization": f"PortOne {portone_secret}"
        }
    )

    if res.status_code != 200:
        raise HTTPException(status_code=400, detail=f"포트원 결제 조회 실패: {res.text}")

    payment = res.json()

    if payment.get("status") != "PAID":
        raise HTTPException(
            status_code=400,
            detail=f"결제가 완료되지 않았습니다. 현재 상태: {payment.get('status')}"
        )

    paid_amount = payment.get("amount", {}).get("total")

    if paid_amount != data.amount:
        raise HTTPException(
            status_code=400,
            detail=f"결제 금액이 일치하지 않습니다. 결제금액: {paid_amount}, 요청금액: {data.amount}"
        )

    return {
        "success": True,
        "paymentId": data.paymentId,
        "orderId": data.orderId
    }

@router.get("/{user_id}")
def get_bookings(user_id: int, db: Session = Depends(get_db)):
    mentor = db.query(Mentor).filter((Mentor.user_id == user_id) | (Mentor.id == user_id)).first()
    mentor_id = mentor.id if mentor else -1

    bookings = db.query(Booking).filter(
        (Booking.status == "CONFIRMED"),
        ((Booking.user_id == user_id) | (Booking.mentor_id == mentor_id) | (Booking.mentor_id == user_id))
    ).order_by(Booking.booking_date.desc()).all()
    
    now = datetime.now()
    result = []
    
    for b in bookings:
        try:
            booking_datetime = datetime.strptime(
                f"{b.booking_date} {b.booking_time}", 
                "%Y-%m-%d %H:%M"
            )
        except:
            booking_datetime = datetime.strptime(
                f"{b.booking_date} {b.booking_time}", 
                "%Y-%m-%d %I:%M %p"
            )
        
        chat_session = db.query(ChatSession).filter(ChatSession.booking_id == b.id).first()
        
        tab_status = "upcoming"
        if chat_session and chat_session.status == "COMPLETED":
            tab_status = "completed"
        elif chat_session and chat_session.status == "ONGOING":
            tab_status = "ongoing"
        else:
            if now < booking_datetime - timedelta(minutes=5):
                tab_status = "upcoming"
            elif booking_datetime - timedelta(minutes=5) <= now <= booking_datetime + timedelta(minutes=30):
                tab_status = "ongoing"
            else:
                tab_status = "completed"
                
        if b.user_id == user_id:
            target_mentor = db.query(Mentor).filter(Mentor.id == b.mentor_id).first()
            partner_name = target_mentor.name if target_mentor else f"멘토 #{b.mentor_id}"
        else:
            target_mentee = db.query(User).filter(User.id == b.user_id).first()
            partner_name = target_mentee.name if target_mentee else "크루(예약자)"
        
        # 💡 [여기에 추가!] 해당 예약에 대한 리뷰가 이미 있는지 확인합니다.
        has_review = db.query(Review).filter(Review.booking_id == b.id).first() is not None

        result.append({
            "id": b.id,
            "mentor_id": b.mentor_id,
            "mentor_name": partner_name, 
            "user_id": b.user_id,
            "booking_date": str(b.booking_date),
            "booking_time": b.booking_time,
            "questions": b.questions,
            "status": b.status,
            "tab_status": tab_status,
            "has_review": has_review, # 💡 [여기에 추가!] 프론트엔드로 전달!
            "created_at": str(b.created_at)
        })

    return result

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