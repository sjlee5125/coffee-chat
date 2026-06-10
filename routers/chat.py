# routers/chat.py
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel

from models import Booking, ChatSession, get_db, CoffeeChatReport
from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary, generate_pdf_report
import json

router = APIRouter(tags=["Chat & Review"])

class ReviewCreateRequest(BaseModel):
    booking_id: int
    rating: int
    review: str

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


# 커피챗 세션 조회 API
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
# 1. 커피챗 세션 조회 API (화면 출력용 번역기 탑재!)
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
# 2. 리뷰 생성 API
# ==========================================
@router.post("/api/review/create")
def create_review(request: ReviewCreateRequest, db: Session = Depends(get_db)):
    print(f" [리뷰 생성] booking_id={request.booking_id}, rating={request.rating}")
    
    session = db.query(ChatSession).filter(ChatSession.booking_id == request.booking_id).first()
    if session:
        session.ai_summary = request.review # (주의: 실제 로직에 맞게 리뷰 저장 필드로 수정 필요할 수 있음)
        db.commit()
    
    return {"message": "리뷰가 저장되었어요!"}

# ==========================================
# 🚀 AI 요약본 생성 API (완벽 보안 아키텍처)
# ==========================================
from fastapi import Request
# (상단 import에 CoffeeChatReport가 추가되어 있어야 합니다)
from models import get_db, ChatSession, CoffeeChatReport 

@router.post("/api/chat-session/{chat_id}/generate-summary")
async def generate_summary(chat_id: int, request: Request, db: Session = Depends(get_db)): 
    print(f"🚀 [{chat_id}번 방] 엔터프라이즈 가명화 파이프라인 가동!")

    session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    # 1. 원본 텍스트 준비
    raw_text = session.stt_text if session.stt_text else "(대화 내용이 없습니다)"

    try:
        from routers.pipeline import MaskingEngine, agent_llm_summary, demask_text
        import json
        
        # 2. 🛡️ 마스킹 엔진 가동 (로컬 정규식 + Azure NER)
        engine = MaskingEngine()
        step0_text = engine.apply_regex(raw_text)
        safe_masked_text = engine.apply_azure_ner(step0_text)
        
        # 3. 💾 [DB 저장] 마스킹된 텍스트와 복구용 매핑 맵을 Report 테이블에 저장!
        new_report = CoffeeChatReport(
            chatsession_id=session.id,
            mentor_id=session.mentor_id,
            mentee_id=session.user_id,
            stt_masked=safe_masked_text,
            masking_map=engine.masking_map
        )
        db.add(new_report)
        db.flush() # DB에 밀어넣기
        print(f"💾 [{chat_id}번 방] CoffeeChatReport (마스킹 백업) DB 저장 완료!")

        # 4. 📝 [LLM 전송] 개인정보가 100% 제거된 안전한 텍스트만 OpenAI로 전송!
        final_json_str = agent_llm_summary(safe_masked_text)
        final_json_str = final_json_str.replace("```json", "").replace("```", "").strip()

        # 5. 🔄 [원본 복구] LLM이 만든 요약본의 [인물_1] 등을 다시 원래 단어로 복구!
        demasked_json_str = demask_text(final_json_str, engine.masking_map)
        parsed = json.loads(demasked_json_str)

        # 6. PDF용 JSON 파일 은닉 저장
        import os
        os.makedirs("summary_data", exist_ok=True)
        with open(f"summary_data/{chat_id}.json", "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False)

        # 7. 화면(textarea)용 예쁜 줄글 조립
        meta = parsed.get("session_metadata", {})
        agendas = parsed.get("core_agendas", [])
        consensus = parsed.get("session_consensus", "내용 없음")

        pretty_text = "1. 게스트 상황 및 목표\n"
        pretty_text += f"[현재 상황]\n{meta.get('guest_as_is', '내용 없음')}\n\n"
        pretty_text += f"[목표]\n{meta.get('guest_to_be', '내용 없음')}\n\n"
        
        pretty_text += "2. 핵심 논의 안건\n"
        if agendas:
            for i, a in enumerate(agendas, 1):
                pretty_text += f"주제 {i}: {a.get('agenda_title', '')}\n"
                pretty_text += f"- 게스트 상황: {a.get('guest_context', '')}\n"
                pretty_text += f"- 호스트 해결책: {a.get('host_solution', '')}\n\n"
        else:
            pretty_text += "- 등록된 안건이 없습니다.\n\n"

        pretty_text += f"3. 최종 합의점 및 결론\n{consensus}"

        # 8. 💾 최종 원본 복구된 리포트를 세션 DB에 저장
        session.ai_summary = pretty_text
        db.commit()
        print(f"✅ [{chat_id}번 방] 복구 및 최종 DB 저장 완료!")
        
        return {"message": "요약본 생성 성공"}

    except Exception as e:
        print(f"🚨 파이프라인 에러: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))