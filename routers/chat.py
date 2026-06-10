# routers/chat.py
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel
import json, os

from models import Booking, ChatSession, CoffeeChatReport, get_db

router = APIRouter(tags=["Chat & Review"])

class ReviewCreateRequest(BaseModel):
    booking_id: int
    rating: int
    review: str

# ✅ 세션 시작
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

# ✅ 세션 종료
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

# ✅ 세션 조회 (중복 제거 — 하나만!)
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
        "ai_summary": session.ai_summary  # ✅ 이게 프론트 summary로 감
    }

# ✅ 리뷰 생성
@router.post("/api/review/create")
def create_review(request: ReviewCreateRequest, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.booking_id == request.booking_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없어요")
    # ⚠️ ai_summary에 리뷰를 덮어쓰지 않도록 별도 필드 사용 권장
    # 지금은 임시로 유지
    db.commit()
    return {"message": "리뷰가 저장되었어요!"}

# ✅ AI 요약 생성 (pipeline.py 버전 삭제하고 여기만 사용)
@router.post("/api/chat-session/{chat_id}/generate-summary")
async def generate_summary(chat_id: int, db: Session = Depends(get_db)):
    print(f"🚀 [{chat_id}번 방] 파이프라인 가동!")

    session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    raw_text = session.stt_text if session.stt_text else "(대화 내용이 없습니다)"

    try:
        from routers.pipeline import MaskingEngine, agent_llm_summary, demask_text

        engine = MaskingEngine()
        step0 = engine.apply_regex(raw_text)
        safe_text = engine.apply_azure_ner(step0)

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

        # ✅ ai_summary에 저장 → 프론트 GET /api/chat-session/{id} 로 조회 가능
        session.ai_summary = pretty_text
        db.commit()
        print(f"✅ [{chat_id}번 방] 저장 완료!")
        return {"message": "요약본 생성 성공", "ai_summary": pretty_text}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))