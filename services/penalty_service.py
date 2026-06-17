from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Mentor, Booking, Notification  # 💡 Notification 모델 임포트 추가
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
        booking.cancelled_by = "sys_noshow" 

        mentor.noshow_count = (mentor.noshow_count or 0) + 1
        count = mentor.noshow_count

        # 페널티 기간 계산
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

        # 💡 [추가] 멘토 노쇼 경고 알림 생성 및 DB 저장
        penalty_days = (mentor.penalty_end_date - now_kst).days
        if mentor.is_banned:
            warn_msg = f"🚨 [영구정지] 누적 노쇼 {count}회로 인해 서비스 이용이 영구 제한됩니다."
        else:
            warn_msg = f"⚠️ [노쇼 경고] 노쇼가 감지되어 {penalty_days}일간 커피챗 일정 등록이 제한됩니다. (누적: {count}회)"

        # Header.jsx가 알림을 읽어갈 수 있도록 Notification 테이블에 삽입
        # 예약 테이블에 기록된 mentor의 user_id(고유번호)를 사용합니다.
        new_notification = Notification(
            user_id=booking.mentor_user_id,  # 멘토 유저의 ID
            message=warn_msg,
            type="PENALTY_WARNING",
            is_read=False,
            created_at=now_kst
        )
        db.add(new_notification)

    elif missing_role == "mentee":
        booking.status = "COMPLETED" 
        booking.mentee_noshow = True
        
        # 💡 [추가] 멘티(일반 유저) 노쇼 경고 알림도 필요하다면 추가
        new_notification = Notification(
            user_id=booking.user_id,  # 멘티 유저의 ID
            message="⚠️ [노쇼 가이드] 신청하신 커피챗에 불참하여 노쇼 처리되었습니다. 신뢰성 있는 이용 부탁드립니다.",
            type="MENTEE_NOSHOW",
            is_read=False,
            created_at=now_kst
        )
        db.add(new_notification)

    else:
        raise ValueError("Invalid missing_role. Must be 'mentor' or 'mentee'")

    db.commit()
    
    return {
        "message": f"{missing_role} 노쇼 처리가 완료되었습니다.",
        "booking_id": booking.id,
        "mentor_noshow_count": mentor.noshow_count if missing_role == "mentor" else None
    }