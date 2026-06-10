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
# 라우터 생성 (prefix를 지정해두면 아래에서 /api/booking 을 생략할 수 있습니다)
router = APIRouter(
    prefix="/api/booking",
    tags=["Bookings"]
)

# 💡 잃어버렸던 userId 필드 완벽 복구!
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
# 1. 커피챗 예약 생성 (async 적용)
# ==========================================================
@router.post("/create")
async def create_booking(request: BookingCreateRequest, db: Session = Depends(get_db)):
    """멘티의 커피챗 예약 생성 API"""
    print(f" [예약 생성 요청] mentor_id={request.mentorId}, user_id={request.userId}")

    # 🚨 [핵심 수리] 엉뚱한 사람을 잡게 만들던 OR(|) 조건을 삭제했습니다!
    # 프론트가 보내준 멘토 고유번호(PK)만 정확하게 조준합니다.
    mentor = db.query(Mentor).filter(Mentor.id == request.mentorId).first()
    
    if not mentor: 
        raise HTTPException(status_code=404, detail="존재하지 않는 멘토입니다.")

    user = db.query(User).filter(User.id == request.userId).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 예약자(유저) 회원입니다.")

    # 🚨 [핵심 수리] 예약 중복 검사에서도 불필요한 OR 조건 제거
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

    # 🚨 [핵심 수리] 가용 시간 삭제에서도 불필요한 OR 조건 제거
    db.query(MentorAvailability).filter(
        MentorAvailability.mentor_id == mentor.id,
        MentorAvailability.date == request.date,
        MentorAvailability.time == request.time,
    ).delete()
    
    db.commit()
    db.refresh(booking)
    print(f" [예약 생성 성공 완결] Booking ID: {booking.id} 매핑 데이터 세팅 완료")

    # ==========================================================
    # 🌟 [알림 기능] 멘토의 진짜 user_id를 찾아 안전하게 100% 발송!
    # ==========================================================
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
# 2. 예약 확정 (멘토가 수락할 때 멘티에게 알림 & 채팅 세션 생성!) 
# ==========================================================
@router.post("/confirm/{booking_id}")
async def confirm_booking(booking_id: int, db: Session = Depends(get_db)):
    """예약 확정 시 멘티에게 실시간 알림 전송 및 채팅 세션 생성 API"""
    print(f" [예약 최종 수락 요청] Booking ID: {booking_id}")
    
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 내역을 찾을 수 없습니다.")
    
    booking.status = "CONFIRMED"
    
    # 🌟 [추가됨] ChatSession 자동 생성 로직
    existing_session = db.query(ChatSession).filter(ChatSession.booking_id == booking_id).first()
    if not existing_session:
        new_session = ChatSession(
            booking_id=booking.id,
            mentor_id=booking.mentor_id,
            user_id=booking.user_id,
            status="READY" # 초기 상태는 READY
        )
        db.add(new_session)

    db.commit()
    print(f" [예약 확정 완료] Booking ID: {booking_id} 상태가 CONFIRMED로 변경 및 세션 생성됨")
    
    # 🌟 [알림 기능] 기존 코드 그대로 유지
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
# 3. 예약 거절 (멘토가 거절할 때 멘티에게 알림!)
# ==========================================================
@router.post("/reject/{booking_id}")
async def reject_booking(booking_id: int, db: Session = Depends(get_db)):
    """예약 거절 시 멘티에게 실시간 알림 전송 API"""
    print(f" [예약 거절 요청] Booking ID: {booking_id}")
    
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 내역을 찾을 수 없습니다.")
    
    # 1. 상태를 REJECTED로 변경
    booking.status = "REJECTED"
    db.commit()
    print(f" [예약 거절 완료] Booking ID: {booking_id} 상태가 REJECTED로 변경됨")
    
    # 2. [알림 기능] 멘티에게 거절 알림 DB 저장 및 실시간 전송
    try:
        new_notif = Notification(
            user_id=booking.user_id, # 예약자(멘티)에게 보냅니다!
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

@router.get("/mentor/{mentor_id}")
def get_mentor_bookings(mentor_id: int, db: Session = Depends(get_db)):
    """
    멘토 대시보드 예약 내역 페이지에 띄울 데이터를 조회합니다.
    (수락 대기 중인 'PAID' 상태의 예약 신청만 골라서 가져옵니다.)
    """
    mentor = db.query(Mentor).filter((Mentor.id == mentor_id) | (Mentor.user_id == mentor_id)).first()
    
    if not mentor:
        return []

    # 💡 [핵심 수정] Booking.status == "PAID" 조건을 추가했습니다!
    # 이제 확정(CONFIRMED)되거나 거절(REJECTED)되어 상태가 바뀐 예약은 아예 조회되지 않습니다.
    bookings = db.query(Booking).filter(
        ((Booking.mentor_id == mentor.id) | (Booking.mentor_id == mentor.user_id)),
        Booking.status == "PAID"
    ).all()

    result = []
    for b in bookings:
        mentee = db.query(User).filter(User.id == b.user_id).first()
        result.append({
            "booking_id": b.id,
            "partner_name": mentee.name if mentee else "익명 크루",   # ← 프론트가 읽는 키
            "partner_image": mentee.profile_image if mentee and hasattr(mentee, 'profile_image') else None,
            "mentee_name": mentee.name if mentee else "익명 크루",    # ← 기존 키 유지 (혹시 다른 곳에서 쓸 수 있으니)
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
        
        # 💡 [추가] 이 예약(booking_id)에 대한 리뷰가 이미 존재하는지 확인
        has_review = db.query(Review).filter(Review.booking_id == b.id).first() is not None
        
        result.append({
            "booking_id": b.id,
            "mentor_id": b.mentor_id,  # 💡 [추가] 프론트엔드에서 리뷰 작성 시 사용할 수 있도록 mentor_id 전달
            "has_review": has_review,  # 💡 [추가] 리뷰 작성 완료 여부 전달
            "partner_name": mentor.name if mentor else "알 수 없는 멘토",
            "partner_image": mentor_user.profile_image if mentor_user and hasattr(mentor_user, 'profile_image') else None,
            "booking_date": str(b.booking_date) if b.booking_date else "", 
            "booking_time": str(b.booking_time) if b.booking_time else "",
            "candidate_times": f"{b.booking_date} {b.booking_time}", 
            "questions": b.questions,
            "status": b.status
        })
    if not bookings:
        return []   
    return result

@router.get("/detail/{booking_id}")  # <-- /api/booking/detail/78
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    # 1. 예약 정보 조회
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 정보를 찾을 수 없습니다.")
    
    # 2. 멘토 정보 및 멘토의 진짜 회원 ID(user_id) 조회
    mentor = db.query(Mentor).filter(Mentor.id == booking.mentor_id).first()
    
    # 3. 멘티(일반 유저) 정보 조회 (이름 추출용)
    mentee_user = db.query(User).filter(User.id == booking.user_id).first()
    
    # 4. 프론트엔드가 판별하기 좋게 커스텀 딕셔너리로 조립해서 반환
    return {
        "id": booking.id,
        "booking_date": str(booking.booking_date),
        "booking_time": booking.booking_time,
        "questions": booking.questions,
        "status": booking.status,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
        
        # 🚨 ID 삼형제 정렬 완료!
        "mentor_id": booking.mentor_id,          # Mentors 테이블 고유번호 (7)
        "mentor_user_id": mentor.user_id if mentor else None,  # Users 테이블 고유번호 (17) 👈 프론트 비교용!
        "user_id": booking.user_id,              # Mentees(Users) 테이블 고유번호 (12)
        
        # 🌟 프론트엔드 opponentName에서 깨지지 않고 이름을 보여주기 위한 데이터 추가
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

    print("PortOne status code:", res.status_code)
    print("PortOne response:", res.text)

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
    print(f" [예약 목록 조회] User ID: {user_id}")
    
    # 💡 멘티로 신청한 내역 + 멘토로서 신청받은 내역을 모두 가져오기 위해 mentor_id 조회
    mentor = db.query(Mentor).filter((Mentor.user_id == user_id) | (Mentor.id == user_id)).first()
    mentor_id = mentor.id if mentor else -1

    # 💡 CONFIRMED(확정) 상태인 예약만 CoffeeChats.jsx 대시보드에 띄웁니다!
    bookings = db.query(Booking).filter(
        (Booking.status == "CONFIRMED"),
        ((Booking.user_id == user_id) | (Booking.mentor_id == mentor_id) | (Booking.mentor_id == user_id))
    ).order_by(Booking.booking_date.desc()).all()
    
    now = datetime.now()
    result = []
    
    for b in bookings:
        # 시간 파싱 (기존 로직 유지)
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
        
        # 🌟 [핵심 변경] ChatSession 상태와 시간 로직을 결합하여 tab_status 결정
        chat_session = db.query(ChatSession).filter(ChatSession.booking_id == b.id).first()
        
        tab_status = "upcoming" # 기본값
        if chat_session and chat_session.status == "COMPLETED":
            tab_status = "completed"
        elif chat_session and chat_session.status == "ONGOING":
            tab_status = "ongoing"
        else:
            # 아직 READY 상태라면, 약속 시간을 기준으로 자동 분류
            if now < booking_datetime - timedelta(minutes=5):
                tab_status = "upcoming"
            elif booking_datetime - timedelta(minutes=5) <= now <= booking_datetime + timedelta(minutes=30):
                tab_status = "ongoing"
            else:
                tab_status = "completed"
                
        # 💡 상대방 이름 파악 (내가 멘티면 상대는 멘토, 내가 멘토면 상대는 멘티)
        if b.user_id == user_id:
            target_mentor = db.query(Mentor).filter(Mentor.id == b.mentor_id).first()
            partner_name = target_mentor.name if target_mentor else f"멘토 #{b.mentor_id}"
        else:
            target_mentee = db.query(User).filter(User.id == b.user_id).first()
            partner_name = target_mentee.name if target_mentee else "크루(예약자)"
        
        result.append({
            "id": b.id,
            "mentor_id": b.mentor_id,
            "mentor_name": partner_name,  # CoffeeChats.jsx는 mentor_name을 아바타 이름으로 씁니다!
            "user_id": b.user_id,
            "booking_date": str(b.booking_date),
            "booking_time": b.booking_time,
            "questions": b.questions,
            "status": b.status,
            "tab_status": tab_status,
            "created_at": str(b.created_at)
        })

    
    return result

@router.post("/review/create")
def create_review(request: ReviewCreateRequest, db: Session = Depends(get_db)):
    # 💡 [추가] 이미 리뷰가 있는지 검사하여 2차 방어막 형성
    existing_review = db.query(Review).filter(Review.booking_id == request.booking_id).first()
    if existing_review:
        raise HTTPException(status_code=400, detail="이미 작성된 리뷰가 있습니다.")

    print(f" [리뷰 생성] booking_id={request.booking_id}, rating={request.rating}, mentor_id={request.mentor_id}")

    # 리뷰 저장
    review = Review(
        booking_id=request.booking_id,
        user_id=request.user_id,
        mentor_id=request.mentor_id,
        rating=request.rating,
        review=request.review
    )
    db.add(review)

    # mentors 테이블 avg_rating 업데이트
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
    print(f" [멘토 리뷰 조회] mentor_id={mentor_id}")
    
    reviews = db.query(Review).filter(Review.mentor_id == mentor_id).all()
    
    result = []
    for r in reviews:
        # 리뷰 작성자 이름 가져오기
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
    # 1. 현재 booking의 mentor 직무 가져오기
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return []
    
    current_mentor = db.query(Mentor).filter(Mentor.id == booking.mentor_id).first()
    if not current_mentor:
        return []
    
    # 2. 같은 직무의 다른 멘토 3명 추천
    similar_mentors = db.query(Mentor).filter(
        Mentor.job_title == current_mentor.job_title,
        Mentor.id != current_mentor.id
    ).limit(3).all()
    
    # 3. 없으면 전체에서 랜덤 3명
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