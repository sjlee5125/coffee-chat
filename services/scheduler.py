from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import SessionLocal # DB 세션 생성용
from models import Booking
from services.penalty_service import process_noshow_penalty

def check_and_apply_noshows():
    """
    1분마다 실행되며 10분이 지난 예약 중 미입장자를 찾아 노쇼 처리합니다.
    """
    db: Session = SessionLocal()
    try:
        now = datetime.now()
        
        # 1. 상태가 PAID(결제완료/예약확정)인 예약만 모두 가져옵니다.
        active_bookings = db.query(Booking).filter(Booking.status == "PAID").all()
        
        for booking in active_bookings:
            # 2. 예약 시간 계산
            scheduled_datetime = datetime.combine(booking.booking_date, booking.booking_time)
            limit_time = scheduled_datetime + timedelta(minutes=10)
            
            # 3. 예약 시간으로부터 10분이 지났다면 검사 시작!
            if now >= limit_time:
                # 멘토가 안 온 경우
                if not booking.is_mentor_entered:
                    process_noshow_penalty(db, booking.id, "mentor")
                
                # 멘티가 안 온 경우
                elif not booking.is_mentee_entered:
                    process_noshow_penalty(db, booking.id, "mentee")
                    
    except Exception as e:
        print(f"🚨 노쇼 스케줄러 실행 중 에러 발생: {e}")
    finally:
        db.close()

# 💡 스케줄러 실행 세팅
scheduler = BackgroundScheduler()
# 1분마다 check_and_apply_noshows 함수를 실행하도록 등록
scheduler.add_job(check_and_apply_noshows, 'interval', minutes=1)