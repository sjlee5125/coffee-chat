from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel

# 💡 CoffeeChatReport 모델을 추가로 임포트합니다.
from models import Booking, ChatSession, CoffeeChatReport, get_db

router = APIRouter(tags=["Chat & Review"])

class ReviewCreateRequest(BaseModel):
    booking_id: int
    rating: int
    review: str  # 이 값이 대화내용 요약본(summary)으로 들어갑니다.

# 커피챗 세션 시작 API
@router.post("/api/chat-session/start")
def start_chat_session(booking_id: int, db: Session = Depends(get_db)):
    print(f" [커피챗 세션 시작] Booking ID: {booking_id}")
    
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 정보를 찾을 수 없어요")
    
    existing = db.query(ChatSession).filter(ChatSession.booking_id == booking_id).first()
    if existing:
        return {"session_id": existing.id, "status": existing.status}
    
    session = ChatSession(
        booking_id=booking_id,
        mentor_id=booking.mentor_id,
        user_id=booking.user_id,
        status="ONGOING",
        started_at=datetime.now()
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    
    return {"session_id": session.id, "status": session.status}


# 커피챗 세션 종료 API
@router.post("/api/chat-session/end/{session_id}")
def end_chat_session(session_id: int, db: Session = Depends(get_db)):
    print(f" [커피챗 세션 종료] Session ID: {session_id}")
    
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없어요")
    
    now = datetime.now()
    session.status = "COMPLETED"
    session.ended_at = now
    if session.started_at:
        session.duration_sec = int((now - session.started_at).total_seconds())
    
    db.commit()
    return {"message": "세션이 종료되었어요", "duration_sec": session.duration_sec}


# 커피챗 세션 조회 API (진행 시간 및 세션 상태 확인용)
@router.get("/api/chat-session/{booking_id}")
def get_chat_session(booking_id: int, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.booking_id == booking_id).first()
    if not session:
        return {"status": "READY"}
    
    return {
        "session_id": session.id,
        "status": session.status,
        "started_at": str(session.started_at) if session.started_at else None,
        "ended_at": str(session.ended_at) if session.ended_at else None,
        "duration_sec": session.duration_sec,
        "stt_text": session.stt_text
    }


# 💡 [핵심 수정] 리뷰 생성 시 coffee_chat_reports 테이블의 summary 컬럼에 저장
@router.post("/api/review/create")
def create_review(request: ReviewCreateRequest, db: Session = Depends(get_db)):
    print(f" [리뷰/요약본 생성] booking_id={request.booking_id}, rating={request.rating}")
    
    # 1. 먼저 매핑된 커피챗 세션이 있는지 확인합니다.
    session = db.query(ChatSession).filter(ChatSession.booking_id == request.booking_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="연동된 채팅 세션을 찾을 수 없습니다.")
    
    # 2. 이미 해당 세션으로 만들어진 리포트가 있는지 확인합니다.
    report = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == session.id).first()
    
    if report:
        # 이미 존재하면 요약 내용만 업데이트
        report.summary = request.review
    else:
        # 없으면 새로운 리포트 레코드를 생성하여 summary 저장
        report = CoffeeChatReport(
            chatsession_id=session.id,
            mentor_id=session.mentor_id,
            mentee_id=session.user_id,  # ChatSession의 user_id가 멘티입니다.
            summary=request.review,
            ai_advice=None  # AI 어드바이스는 나중에 태욱님 파트에서 업데이트
        )
        db.add(report)
        
    db.commit()
    return {"message": "대화 요약본이 리포트에 성공적으로 저장되었어요!"}


# 💡 [신규 추가] 프론트엔드 리포트 페이지 전용 데이터 조회 API
@router.get("/api/coffee-chat-report/{booking_id}")
def get_coffee_chat_report(booking_id: int, db: Session = Depends(get_db)):
    print(f" [리포트 조회] Booking ID: {booking_id}")
    
    # booking_id를 통해 대화 세션을 먼저 찾습니다.
    session = db.query(ChatSession).filter(ChatSession.booking_id == booking_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="대화 세션 내역을 찾을 수 없습니다.")
    
    # 세션 ID를 통해 리포트 데이터를 가져옵니다.
    report = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == session.id).first()
    if not report:
        # 생성된 리포트가 아직 없더라도 프론트가 에러 나지 않게 빈 구조를 던져줍니다.
        return {"summary": None, "ai_advice": None}
    
    return {
        "report_id": report.id,
        "chatsession_id": report.chatsession_id,
        "mentor_id": report.mentor_id,
        "mentee_id": report.mentee_id,
        "stt_masked": report.stt_masked,
        "summary": report.summary,       # 👈 프론트의 setSummary로 들어갈 데이터
        "ai_advice": report.ai_advice    # 👈 프론트의 setAiAdvice로 들어갈 데이터
    }