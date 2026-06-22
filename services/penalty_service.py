from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Mentor, Booking, Notification  # 💡 Notification 모델 임포트
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

        # 🌟 [알림 1] 호스트(멘토) 노쇼 경고 및 패널티 알림
        penalty_days = (mentor.penalty_end_date - now_kst).days
        if mentor.is_banned:
            warn_msg = f"🚨 [영구정지] 누적 노쇼 {count}회로 인해 서비스 이용이 영구 제한됩니다."
        else:
            warn_msg = f"⚠️ [패널티] 노쇼가 감지되어 {penalty_days}일간 커피챗 일정 등록이 제한됩니다. (누적: {count}회)"

        notif_mentor = Notification(
            user_id=mentor.user_id,  # 💡 정확한 User ID 매핑
            message=warn_msg,
            type="PENALTY_APPLIED",  # 💡 프론트엔드의 일정관리 탭으로 라우팅
            booking_id=booking.id,   # 💡 해당 예약 정보 삽입
            is_read=False,
            created_at=now_kst
        )
        db.add(notif_mentor)

        # 🌟 [알림 2] 불참 피해를 입은 멘티(게스트)에게 취소 및 환불 알림
        formatted_time = b_time.strftime("%H:%M")
        notif_mentee = Notification(
            user_id=booking.user_id,
            message=f"💸 호스트의 불참(노쇼)으로 {b_date} {formatted_time} 예약이 취소되었습니다. 결제 금액은 전액 환불됩니다.",
            type="REFUND_ISSUED",    # 💡 프론트엔드의 취소내역 탭으로 라우팅
            booking_id=booking.id,
            is_read=False,
            created_at=now_kst
        )
        db.add(notif_mentee)

    elif missing_role == "mentee":
        # 멘티 노쇼는 호스트가 정상 접속했으므로 거래 완료(COMPLETED) 처리하여 호스트에게 정산되도록 함
        booking.status = "COMPLETED" 
        booking.mentee_noshow = True
        
        # 🌟 [알림 3] 멘티(게스트) 본인에게 노쇼 경고 (환불 불가)
        formatted_time = b_time.strftime("%H:%M")
        new_notification = Notification(
            user_id=booking.user_id,
            message=f"⚠️ [노쇼] {b_date} {formatted_time} 커피챗에 불참하여 노쇼 처리되었습니다. (결제 금액 환불 불가)",
            type="MENTEE_NOSHOW",
            booking_id=booking.id,
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