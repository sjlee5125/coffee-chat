from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Mentor, Booking
from fastapi import HTTPException

def process_noshow_penalty(db: Session, booking_id: int, missing_role: str):
    """
    10분 미입장 시 호출되는 노쇼 처리 로직
    :param missing_role: "mentor" 또는 "mentee"
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")

    # ════════════════════════════════════════════════════════════════
    # 🔒 [시간 검증 로직] 정말 10분이 지났는지 확인!
    # ════════════════════════════════════════════════════════════════
    scheduled_datetime = datetime.combine(booking.booking_date, booking.booking_time)
    now = datetime.now() # KST 기준
    limit_time = scheduled_datetime + timedelta(minutes=10)
    
    if now < limit_time:
        raise HTTPException(
            status_code=400, 
            detail=f"아직 노쇼 신고를 할 수 없습니다. (신고 가능 시간: {limit_time.strftime('%H:%M')} 이후)"
        )

    # ════════════════════════════════════════════════════════════════
    # 🔴 [핵심 로직] 멘토 노쇼 처리
    # ════════════════════════════════════════════════════════════════
    if missing_role == "mentor":
        mentor = db.query(Mentor).filter(Mentor.id == booking.mentor_id).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="멘토를 찾을 수 없습니다.")

        # 1. 예약 상태 업데이트 및 환불 처리(개념적)
        booking.status = "CANCELLED"
        booking.mentor_noshow = True
        booking.cancelled_at = now
        booking.cancelled_by = "system_mentor_noshow"

        # 2. 멘토 노쇼 횟수 증가
        mentor.noshow_count = (mentor.noshow_count or 0) + 1
        count = mentor.noshow_count

        # 3. 횟수에 따른 패널티 차등 부여
        if 1 <= count <= 3:
            mentor.penalty_end_date = now + timedelta(days=3)
        elif 4 <= count <= 6:
            mentor.penalty_end_date = now + timedelta(days=7)
        elif 7 <= count <= 9:  
            mentor.penalty_end_date = now + timedelta(days=30)
        elif count >= 10:
            mentor.is_banned = True
            mentor.penalty_end_date = now + timedelta(days=36500) # 사실상 영구 정지
            mentor.status = "BANNED"

    # ════════════════════════════════════════════════════════════════
    # 🔵 [핵심 로직] 멘티 노쇼 처리
    # ════════════════════════════════════════════════════════════════
    elif missing_role == "mentee":
        # 1. 멘티가 안 왔으므로 멘토에게는 정상 지급 처리 (상태를 COMPLETED로 하되 노쇼 마킹)
        booking.status = "COMPLETED" 
        booking.mentee_noshow = True

    else:
        raise ValueError("Invalid missing_role. Must be 'mentor' or 'mentee'")

    # DB 반영
    db.commit()
    
    return {
        "message": f"{missing_role} 노쇼 처리가 완료되었습니다.",
        "booking_id": booking.id,
        "mentor_noshow_count": mentor.noshow_count if missing_role == "mentor" else None
    }