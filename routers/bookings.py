from pydantic import BaseModel
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import User, Mentor, Booking, MentorAvailability, Notification, get_db
from routers.notifications import manager 
from datetime import datetime, timedelta
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
# 2. 예약 확정 (멘토가 수락할 때 멘티에게 알림!) (async 적용)
# ==========================================================
@router.post("/confirm/{booking_id}")
async def confirm_booking(booking_id: int, db: Session = Depends(get_db)):
    """예약 확정 시 멘티에게 실시간 알림 전송 API"""
    print(f" [예약 최종 수락 요청] Booking ID: {booking_id}")
    
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 내역을 찾을 수 없습니다.")
    
    booking.status = "CONFIRMED"
    db.commit()
    print(f" [예약 확정 완료] Booking ID: {booking_id} 상태가 CONFIRMED로 변경됨")
    
    # 🌟 [알림 기능] 확정 알림도 DB에 저장하고 멘티에게 전송!
    try:
        new_notif = Notification(
            user_id=booking.user_id, # 이번엔 예약자(멘티)에게 보냅니다!
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
@router.get("/mentor/{mentor_id}")
def get_mentor_bookings(mentor_id: int, db: Session = Depends(get_db)):
    """
    멘토 대시보드 예약 내역 페이지에 띄울 데이터를 조회합니다.
    (멘토 ID를 기준으로 해당 멘토에게 들어온 모든 예약 신청을 가져옵니다.)
    """
    # 멘토가 User 테이블의 id를 쓰고 있는지 Mentor 테이블의 id를 쓰고 있는지에 맞춰 조회
    mentor = db.query(Mentor).filter((Mentor.id == mentor_id) | (Mentor.user_id == mentor_id)).first()
    
    # ❌ 404 에러를 던지던 로직 삭제
    # ✅ 멘토가 아니면 에러 대신 조용히 빈 리스트([])를 반환합니다.
    if not mentor:
        return []

    bookings = db.query(Booking).filter(
        (Booking.mentor_id == mentor.id) | (Booking.mentor_id == mentor.user_id)
    ).all()

    result = []
    for b in bookings:
        mentee = db.query(User).filter(User.id == b.user_id).first()
        result.append({
            "booking_id": b.id,
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
    bookings = db.query(Booking).filter(Booking.user_id == user_id).all()

    result = []
    for b in bookings:
        mentor = db.query(Mentor).filter(Mentor.id == b.mentor_id).first()
        mentor_user = db.query(User).filter(User.id == mentor.user_id).first() if mentor else None
        
        result.append({
            "booking_id": b.id,
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
@router.get("/{user_id}")
def get_bookings(user_id: int, db: Session = Depends(get_db)):
    print(f" [예약 목록 조회] User ID: {user_id}")
    
    bookings = db.query(Booking).filter(
        Booking.user_id == user_id
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
        
        # 시간 기준으로 상태 자동 분류
        if now < booking_datetime - timedelta(minutes=5):
            tab_status = "upcoming"
        elif booking_datetime - timedelta(minutes=5) <= now <= booking_datetime + timedelta(minutes=30):
            tab_status = "ongoing"
        else:
            tab_status = "completed"
            
        try:
            mentor = db.query(Mentor).filter(Mentor.id == b.mentor_id).first()
            real_mentor_name = mentor.name if mentor else f"멘토 #{b.mentor_id}"
        except:
            real_mentor_name = f"멘토 #{b.mentor_id}"
        
        result.append({
            "id": b.id,
            "mentor_id": b.mentor_id,
            "mentor_name": real_mentor_name,
            "user_id": b.user_id,
            "booking_date": str(b.booking_date),
            "booking_time": b.booking_time,
            "questions": b.questions,
            "status": b.status,
            "tab_status": tab_status,
            "created_at": str(b.created_at)
        })
    
    return result