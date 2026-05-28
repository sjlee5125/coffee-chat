import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import User, Mentor, Booking, MentorAvailability, get_db
from schemas import BookingCreateRequest

# 💡 위에서 만든 알림 매니저를 가져옵니다.
from routers.notifications import manager 

# 라우터 생성 (prefix를 지정해두면 아래에서 /api/booking 을 생략할 수 있습니다)
router = APIRouter(
    prefix="/api/booking",
    tags=["Bookings"]
)

@router.post("/create")
def create_booking(request: BookingCreateRequest, db: Session = Depends(get_db)):
    """멘티의 커피챗 예약 생성 API"""
    print(f" [예약 생성 요청] mentor_id={request.mentorId}, user_id={request.userId}, date={request.date}, time={request.time}")

    mentor = db.query(Mentor).filter((Mentor.id == request.mentorId) | (Mentor.user_id == request.mentorId)).first()
    if not mentor: 
        raise HTTPException(status_code=404, detail="존재하지 않는 멘토입니다.")

    user = db.query(User).filter(User.id == request.userId).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 예약자(유저) 회원입니다.")

    existing = db.query(Booking).filter(
        ((Booking.mentor_id == mentor.id) | (Booking.mentor_id == mentor.user_id)),
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
        ((MentorAvailability.mentor_id == mentor.id) | (MentorAvailability.mentor_id == mentor.user_id)),
        MentorAvailability.date == request.date,
        MentorAvailability.time == request.time,
    ).delete()

    db.commit()
    db.refresh(booking)
    print(f" [예약 생성 성공 완결] Booking ID: {booking.id} 매핑 데이터 세팅 완료")

    try:
        # 분리해둔 매니저를 통해 알림 전송!
        asyncio.create_task(manager.send_personal_message(
            {"type": "NEW_NOTIFICATION", "message": "🎉 새로운 커피챗 예약 요청이 도착했습니다!"}, 
            mentor.user_id
        ))
    except Exception as ws_err:
        print(f" [알림 전송 실패 비치명적 에러]: {str(ws_err)}")

    return {"message": "예약이 완료되었습니다.", "booking_id": booking.id}
# routers/bookings.py 맨 아래에 이 함수 하나만 남겨두세요.

@router.post("/confirm/{booking_id}")
def confirm_booking(booking_id: int, db: Session = Depends(get_db)):
    """
    멘토가 대시보드에서 예약을 최종 수락(CONFIRMED)하는 API
    예약 확정 시 멘티에게 실시간 알림을 보냅니다.
    """
    print(f" [예약 최종 수락 요청] Booking ID: {booking_id}")
    
    # 1. 예약 내역 조회
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 내역을 찾을 수 없습니다.")
    
    # 2. 상태를 CONFIRMED로 승격
    booking.status = "CONFIRMED"
    db.commit()
    print(f" [예약 확정 완료] Booking ID: {booking_id} 상태가 CONFIRMED로 변경됨")
    
    # 3. 💡 예약 확정 알림 (멘티에게 전송)
    try:
        asyncio.create_task(manager.send_personal_message(
            {
                "type": "BOOKING_CONFIRMED", 
                "message": "🎉 멘토님이 커피챗 예약을 최종 확정했습니다!",
                "booking_id": booking_id
            }, 
            booking.user_id # 예약자인 멘티에게 알림 발송
        ))
    except Exception as ws_err:
        print(f" [알림 전송 실패]: {str(ws_err)}")
    
    return {"message": "커피챗 예약이 최종 확정되었습니다."}