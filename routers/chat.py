import os
import json
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

# 필요한 모델들 임포트
from models import Booking, ChatSession, CoffeeChatReport, Review, Mentor, User, get_db
from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary, generate_pdf_report

# 💡 [핵심] 라우터 선언은 파일 맨 위에서 딱 한 번만 해야 합니다!
router = APIRouter(tags=["Chat & Review"])

class ReviewCreateRequest(BaseModel):
    booking_id: int
    rating: int
    review: str  # 게스트가 작성한 한 줄 평 후기


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
# 5. AI 요약본 생성 API 
# ==========================================
@router.post("/api/chat-session/{chat_id}/generate-summary")
async def generate_summary(chat_id: int, request: Request, db: Session = Depends(get_db)): 
    print(f"🚀 [{chat_id}번 방] 파이프라인 가동! (PDF용 JSON 및 줄글 생성)")

    session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    
    if session and session.stt_text:
        raw_text = session.stt_text
    else:
        raw_text = """Host: 아, 아. 네, 아름 님 안녕하세요. 목소리 잘 들리시나요?
        Guest: 아, 네! 성현 님 안녕하세요. 아주 잘 들립니다! 퇴근하시고 피곤하실 텐데 이렇게 시간 내주셔서 정말 감사드려요."""

    try:
        from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary
        
        step0_text = agent_regex_masking(raw_text)
        step1_text = agent_azure_pii(step0_text)
        step2_text = agent_llm_masking(step1_text)
        final_json_str = agent_llm_summary(step2_text)

        final_json_str = final_json_str.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(final_json_str)

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
            pretty_text += f"- 게스트 상황/질문: {a.get('guest_context', '')}\n"
            pretty_text += f"- 호스트 해결책: {a.get('host_solution', '')}\n\n"
        pretty_text += f"3. 최종 합의점 및 결론\n{consensus}"

        if session:
            session.ai_summary = pretty_text  
            
            report = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == session.id).first()
            if report:
                report.summary = pretty_text
                
            db.commit()
        
        return {"message": "요약본 생성 성공", "ai_summary": pretty_text}

    except Exception as e:
        print(f"🚨 파이프라인 에러 발생: {e}")
        raise HTTPException(status_code=500, detail=f"요약본 생성 중 서버 에러: {str(e)}")


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


# ==========================================
# 8. AI 페이스메이커 어드바이스 (404 에러 원인 제거 및 통합 완료)
# ==========================================
@router.post("/api/wrap-up/{chat_id}")
async def get_wrapup_report(chat_id: int, db: Session = Depends(get_db)):
    booking_id = chat_id
    print(f"🔄 [AI 랩업 리포트 생성 요청] Booking ID: {booking_id} 번으로 조회를 시작합니다.")
    
    # 1. 징검다리인 ChatSession 테이블에서 booking_id로 검색
    session = db.query(ChatSession).filter(ChatSession.booking_id == booking_id).first()
    if not session:
        print(f"❌ [404 에러 발생 원인] DB에 Booking ID {booking_id} 번과 연결된 ChatSession 레코드가 아예 없습니다!")
        raise HTTPException(
            status_code=404, 
            detail=f"예약 번호({booking_id})와 연동된 채팅 세션(ChatSession) 데이터가 DB에 없습니다. 세션 시작/종료가 정상 처리되었는지 확인하세요."
        )
    
    # 2. 찾아낸 session.id를 가지고 CoffeeChatReport 테이블 조회
    report_record = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == session.id).first()
    if not report_record:
        print(f"❌ [404 에러 발생 원인] ChatSession(ID: {session.id})은 찾았으나, 이와 연결된 CoffeeChatReport 레코드가 DB에 없습니다!")
        raise HTTPException(
            status_code=404, 
            detail=f"채팅 세션 번호({session.id})와 연동된 리포트 데이터(CoffeeChatReport)가 DB에 존재하지 않습니다."
        )
    
    # 3. 마스킹된 텍스트가 존재하는지 확인
    if not report_record.stt_masked:
        print(f"⚠️ [400 에러 발생 원인] 데이터들은 매칭되었으나, 리포트 내부의 stt_masked(마스킹 대화록) 컬럼이 완전히 비어있습니다.")
        raise HTTPException(
            status_code=400, 
            detail="마스킹 처리된 대화록(stt_masked)이 아직 준비되지 않았습니다. 실시간 STT 데이터 전송 상태를 확인하세요."
        )
    
    # 4. 이미 저장된 결과가 있는지 확인 (캐시)
    if report_record.ai_advice:
        print(f"💾 [캐시 사용] 이미 생성된 AI 어드바이스가 존재하여 즉시 반환합니다. Booking ID: {booking_id}")
        return {"status": "success", "report": report_record.ai_advice}

    try:
        from routers.ai_service import generate_wrapup_report 
        
        print(f"🤖 [LLM 호출] 세션 {session.id}번의 stt_masked 데이터를 기반으로 GPT 분석을 요청합니다...")
        ai_report = generate_wrapup_report(host_text=report_record.stt_masked, guest_text="")
        
        report_record.ai_advice = ai_report
        db.commit()
        print(f"✅ [DB 저장 완료] Booking ID: {booking_id} 번 리포트에 ai_advice 저장을 완료했습니다.")
        
        return {"status": "success", "report": ai_report}

    except Exception as e:
        db.rollback()
        print(f"🚨 [AI 리포트 생성 실패] OpenAI 연동 혹은 문맥 처리 중 예외 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI 어드바이스 생성 중 오류 발생: {str(e)}")