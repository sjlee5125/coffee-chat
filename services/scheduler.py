from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Booking
from services.penalty_service import process_noshow_penalty

def check_and_apply_noshows():
    """
    1분마다 실행되며 10분이 지난 예약 중 미입장자를 찾아 노쇼 처리합니다.
    """
    db: Session = SessionLocal()
    try:
        # 💡 [핵심] 서버 설정과 무관하게 무조건 한국 시간(KST)으로 계산!
        now_kst = datetime.utcnow() + timedelta(hours=9)
        
        # 💡 [핵심] PAID 뿐만 아니라 CONFIRMED 상태인 예약도 찾아옵니다!
        active_bookings = db.query(Booking).filter(Booking.status.in_(["PAID", "CONFIRMED"])).all()
        
        for booking in active_bookings:
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
            limit_time = scheduled_datetime + timedelta(minutes=10)
            
            # 💡 한국 시간(now_kst) 기준으로 10분 초과 여부 확인
            if now_kst >= limit_time:
                # 멘토가 안 온 경우
                if not getattr(booking, 'is_mentor_entered', False) and not booking.mentor_noshow:
                    process_noshow_penalty(db, booking.id, "mentor")
                
                # 멘토는 왔는데 멘티가 안 온 경우
                elif getattr(booking, 'is_mentor_entered', False) and not getattr(booking, 'is_mentee_entered', False) and not booking.mentee_noshow:
                    process_noshow_penalty(db, booking.id, "mentee")
                    
    except Exception as e:
        print(f"🚨 노쇼 스케줄러 실행 중 에러 발생: {e}")
    finally:
        db.close()
logging.getLogger('apscheduler').setLevel(logging.WARNING)

scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(check_and_apply_noshows, 'interval', minutes=1)