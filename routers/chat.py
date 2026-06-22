import os
import json
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
# 필요한 모델들 임포트
from models import Booking, ChatSession, CoffeeChatReport, Review, Mentor, User, get_db
from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary, generate_pdf_report

router = APIRouter(tags=["Chat & Review"])

class ReviewCreateRequest(BaseModel):
    booking_id: int
    rating: int
    review: str  # 게스트가 작성한 한 줄 평 후기
class TranscriptRequest(BaseModel):
    transcript: str

# ==========================================
# 1. 커피챗 세션 시작 API
# ==========================================
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


# ==========================================
# 2. 커피챗 세션 종료 API
# ==========================================
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
    
    # 중복 생성 방지 및 리포트 기본 뼈대 매핑
    report = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == session.id).first()
    if not report:
        report = CoffeeChatReport(
            chatsession_id=session.id,
            mentor_id=session.mentor_id,
            mentee_id=session.user_id,
            summary=None,               
            ai_advice=None,             
            stt_masked=None             
        )
        db.add(report)
        db.flush()  

    db.commit()
    return {
        "message": "세션이 성공적으로 종료되었으며, 리포트 기본 뼈대가 매핑되었습니다.", 
        "duration_sec": session.duration_sec
    }


# ==========================================
# 3. 커피챗 세션 조회 API
# ==========================================
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
        "stt_text": session.stt_text,
        "ai_summary": session.ai_summary
    }


# ==========================================
# 4. 리뷰 생성 API
# ==========================================
@router.post("/api/review/create")
def create_review(request: ReviewCreateRequest, db: Session = Depends(get_db)):
    print(f" [리뷰 생성 요청] booking_id={request.booking_id}, rating={request.rating}")
    
    existing_review = db.query(Review).filter(Review.booking_id == request.booking_id).first()
    if existing_review:
        raise HTTPException(status_code=400, detail="이미 이 커피챗에 대한 리뷰를 작성하셨습니다.")
    
    session = db.query(ChatSession).filter(ChatSession.booking_id == request.booking_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="연동된 채팅 세션을 찾을 수 없습니다.")
    
    new_review = Review(
        booking_id=request.booking_id,
        mentor_id=session.mentor_id,
        user_id=session.user_id,  
        rating=request.rating,
        review=request.review
    )
    db.add(new_review)
    
    # 멘토 평균 평점 자동 갱신
    mentor = db.query(Mentor).filter(Mentor.id == session.mentor_id).first()
    if mentor:
        reviews = db.query(Review).filter(Review.mentor_id == session.mentor_id).all()
        total_rating = sum(r.rating for r in reviews) + request.rating
        review_count = len(reviews) + 1
        mentor.avg_rating = total_rating / review_count

    db.commit()
    return {"message": "리뷰가 저장되었어요!"}


# ==========================================
# 5. AI 요약본 생성 API (마스킹 내역 & 매핑 데이터 저장 반영 ✨)
# ==========================================

# ==========================================
# 6. PDF 다운로드 API
# ==========================================
@router.get("/api/chat-session/{chat_id}/summary-pdf")
async def download_summary_pdf(chat_id: int, db: Session = Depends(get_db)):
    json_file_path = f"summary_data/{chat_id}.json"
    if not os.path.exists(json_file_path):
        raise HTTPException(status_code=404, detail="요약 데이터가 없습니다.")
    
    with open(json_file_path, "r", encoding="utf-8") as f:
        parsed = json.load(f)
    
    pdf_path = f"summary_{chat_id}.pdf"
    generate_pdf_report(parsed, pdf_path)
    return FileResponse(pdf_path, media_type="application/pdf", filename="커피챗_상세리포트.pdf")


# ==========================================
# 7. 프론트엔드 리포트 페이지 전용 데이터 조회 API
# ==========================================
@router.get("/api/coffee-chat-report/{booking_id}")
def get_coffee_chat_report(booking_id: int, db: Session = Depends(get_db)):
    print(f" [리포트 조회] Booking ID: {booking_id}")
    
    session = db.query(ChatSession).filter(ChatSession.booking_id == booking_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="대화 세션 내역을 찾을 수 없습니다.")
    
    report = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == session.id).first()
    if not report:
        return {"summary": None, "ai_advice": None}
    
    return {
        "report_id": report.id,
        "chatsession_id": report.chatsession_id,
        "mentor_id": report.mentor_id,
        "mentee_id": report.mentee_id,
        "stt_masked": report.stt_masked,
        "summary": report.summary,       
        "ai_advice": report.ai_advice    
    }
@router.post("/api/chat-session/{session_id}/save-transcript")
def save_transcript(session_id: int, req: TranscriptRequest, db: Session = Depends(get_db)):
    chat_session = db.query(ChatSession).filter(ChatSession.id == session_id).first() # 💡 session_id를 id로 수정!
    if chat_session:
        chat_session.stt_text = req.transcript
        db.commit()
        return {"status": "success"}
    return {"status": "error", "message": "세션 없음"}

# 2. 튕겼다가 다시 접속 시: DB에 저장된 대화 내용 불러오기
@router.get("/api/chat-session/{session_id}/transcript")
def get_transcript(session_id: int, db: Session = Depends(get_db)):
    chat_session = db.query(ChatSession).filter(ChatSession.id == session_id).first() # 💡 session_id를 id로 수정!
    if chat_session and chat_session.stt_text:
        return {"transcript": chat_session.stt_text}
    return {"transcript": ""}