# routers/chat.py
import os
import json
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

# 중복 임포트 제거 및 깔끔하게 정리
from models import Booking, ChatSession, CoffeeChatReport, get_db
from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary, generate_pdf_report, MaskingEngine, demask_text

router = APIRouter(tags=["Chat & Review"])

class ReviewCreateRequest(BaseModel):
    booking_id: int
    rating: int
    review: str  # 이 값이 대화내용 요약본(summary)으로 들어갑니다.


# ==========================================
# ✅ 세션 시작 API
# ==========================================
@router.post("/api/chat-session/start")
def start_chat_session(booking_id: int, db: Session = Depends(get_db)):
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
# ✅ 세션 종료 API
# ==========================================
@router.post("/api/chat-session/end/{session_id}")
def end_chat_session(session_id: int, db: Session = Depends(get_db)):
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


# ==========================================
# 1. 커피챗 세션 조회 API (화면 출력용 번역기 탑재)
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
# 2. 리뷰(요약본) 생성 API 
# ==========================================
@router.post("/api/review/create")
def create_review(request: ReviewCreateRequest, db: Session = Depends(get_db)):
    print(f" [리뷰/요약본 생성] booking_id={request.booking_id}, rating={request.rating}")
    
    session = db.query(ChatSession).filter(ChatSession.booking_id == request.booking_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="연동된 채팅 세션을 찾을 수 없습니다.")
    
    report = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == session.id).first()
    
    if report:
        report.summary = request.review
    else:
        report = CoffeeChatReport(
            chatsession_id=session.id,
            mentor_id=session.mentor_id,
            mentee_id=session.user_id, 
            summary=request.review,
            ai_advice=None  
        )
        db.add(report)
        
    db.commit()
    return {"message": "대화 요약본이 리포트에 성공적으로 저장되었어요!"}


# ==========================================
# ✅ AI 요약 생성 파이프라인 (500 에러 해결!)
# ==========================================
@router.post("/api/chat-session/{chat_id}/generate-summary")
async def generate_summary(chat_id: int, db: Session = Depends(get_db)):
    print(f"🚀 [{chat_id}번 방] 파이프라인 가동!")

    session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    raw_text = session.stt_text if session.stt_text else "(대화 내용이 없습니다)"

    try:
        engine = MaskingEngine()
        step0 = engine.apply_regex(raw_text)
        safe_text = engine.apply_azure_ner(step0)

        # 💡 [핵심 수정] 무조건 새로 만들지 않고, 기존 리포트가 있으면 업데이트합니다!
        existing_report = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == session.id).first()
        
        if existing_report:
            existing_report.stt_masked = safe_text
            existing_report.masking_map = engine.masking_map
        else:
            new_report = CoffeeChatReport(
                chatsession_id=session.id,
                mentor_id=session.mentor_id,
                mentee_id=session.user_id,
                stt_masked=safe_text,
                masking_map=engine.masking_map
            )
            db.add(new_report)
            
        db.flush()

        final_json_str = agent_llm_summary(safe_text)
        final_json_str = final_json_str.replace("```json", "").replace("```", "").strip()
        demasked = demask_text(final_json_str, engine.masking_map)
        parsed = json.loads(demasked)

        os.makedirs("summary_data", exist_ok=True)
        with open(f"summary_data/{chat_id}.json", "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False)

        meta = parsed.get("session_metadata", {})
        agendas = parsed.get("core_agendas", [])
        consensus = parsed.get("session_consensus", "내용 없음")

        pretty_text = "1. 게스트 상황 및 목표\n"
        pretty_text += f"[현재 상황]\n{meta.get('guest_as_is', '내용 없음')}\n\n"
        pretty_text += f"[목표]\n{meta.get('guest_to_be', '내용 없음')}\n\n"
        pretty_text += "2. 핵심 논의 안건\n"
        for i, a in enumerate(agendas, 1):
            pretty_text += f"주제 {i}: {a.get('agenda_title', '')}\n"
            pretty_text += f"- 게스트 상황: {a.get('guest_context', '')}\n"
            pretty_text += f"- 호스트 해결책: {a.get('host_solution', '')}\n\n"
        pretty_text += f"3. 최종 합의점 및 결론\n{consensus}"

        session.ai_summary = pretty_text
        db.commit()
        print(f"✅ [{chat_id}번 방] 저장 완료!")
        return {"message": "요약본 생성 성공", "ai_summary": pretty_text}

    except Exception as e:
        print(f"🚨 파이프라인 에러 발생: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"요약본 생성 중 서버 에러: {str(e)}")


# ==========================================
# 4. PDF 다운로드 API 
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
# 5. 리포트 페이지 전용 데이터 조회 API 
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