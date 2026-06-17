from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Mentor, Booking
from fastapi import HTTPException

def process_noshow_penalty(db: Session, booking_id: int, missing_role: str):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")

    b_date = booking.booking_date
    b_time = booking.booking_time
    
    if isinstance(b_date, str):
        b_date = datetime.strptime(b_date, "%Y-%m-%d").date()
    if isinstance(b_time, str):
        try:
            b_time = datetime.strptime(b_time, "%H:%M:%S").time()
        except ValueError:
            b_time = datetime.strptime(b_time, "%H:%M").time()

    scheduled_datetime = datetime.combine(b_date, b_time)
    
    # 💡 [핵심] 여기서도 무조건 한국 시간(KST)으로 계산!
    now_kst = datetime.utcnow() + timedelta(hours=9) 
    limit_time = scheduled_datetime + timedelta(minutes=10)
    
    if now_kst < limit_time:
        raise HTTPException(
            status_code=400, 
            detail=f"아직 노쇼 신고를 할 수 없습니다. (신고 가능 시간: {limit_time.strftime('%H:%M')} 이후)"
        )

    if missing_role == "mentor":
        mentor = db.query(Mentor).filter(Mentor.id == booking.mentor_id).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="멘토를 찾을 수 없습니다.")

        booking.status = "CANCELLED"
        booking.mentor_noshow = True
        booking.cancelled_at = now_kst
        
        # 💡 [핵심] DB 에러 방지를 위해 10글자 이하로 수정!
        booking.cancelled_by = "sys_noshow" 

        mentor.noshow_count = (mentor.noshow_count or 0) + 1
        count = mentor.noshow_count

        if 1 <= count <= 3:
            mentor.penalty_end_date = now_kst + timedelta(days=3)
        elif 4 <= count <= 6:
            mentor.penalty_end_date = now_kst + timedelta(days=7)
        elif 7 <= count <= 9:  
            mentor.penalty_end_date = now_kst + timedelta(days=30)
        elif count >= 10:
            mentor.is_banned = True
            mentor.penalty_end_date = now_kst + timedelta(days=36500)
            mentor.status = "BANNED"

    elif missing_role == "mentee":
        booking.status = "COMPLETED" 
        booking.mentee_noshow = True

    else:
        raise ValueError("Invalid missing_role. Must be 'mentor' or 'mentee'")

    db.commit()
    
    return {
        "message": f"{missing_role} 노쇼 처리가 완료되었습니다.",
        "booking_id": booking.id,
        "mentor_noshow_count": mentor.noshow_count if missing_role == "mentor" else None
    }