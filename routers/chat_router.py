from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
# 🌟 ChatSession 테이블도 읽어야 하므로 import 목록에 추가해 줍니다.
from models import CoffeeChatReport, ChatSession, get_db
from .ai_service import generate_wrapup_report 

router = APIRouter()

@router.post("/api/wrap-up/{chat_id}")
async def get_wrapup_report(chat_id: int, db: Session = Depends(get_db)):
    print(f"🔄 [AI 랩업 리포트 생성 요청] 넘어온 URL 번호(booking_id): {chat_id}")
    
    # 🌟 [수정된 핵심 로직 1단계] 
    # 프론트에서 넘어온 번호(chat_id)가 사실은 booking_id 이므로, 
    # 먼저 chat_sessions 테이블에서 이 예약 번호를 가진 진짜 세션을 찾습니다.
    chat_session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    
    if not chat_session:
        raise HTTPException(status_code=404, detail="해당 예약 번호와 연결된 채팅 세션을 찾을 수 없습니다.")
    
    # 🌟 [수정된 핵심 로직 2단계]
    # 찾은 진짜 세션의 ID(chat_session.id)를 이용해서 리포트 테이블을 검색합니다!
    real_session_id = chat_session.id
    print(f"🔍 진짜 chatsession_id를 찾았습니다: {real_session_id}")
    
    report_record = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == real_session_id).first()
    
    # --- (여기서부터 아래는 기존과 완전히 똑같습니다!) ---
    
    if not report_record:
        raise HTTPException(status_code=404, detail="해당 커피챗의 리포트 데이터를 찾을 수 없습니다.")
    
    if not report_record.stt_masked:
        raise HTTPException(status_code=400, detail="마스킹 처리된 대화록(stt_masked)이 아직 준비되지 않았습니다.")
    
    if report_record.ai_advice:
        print(f"💾 [캐시 사용] 이미 생성된 AI 어드바이스가 존재하여 DB 데이터를 즉시 반환합니다.")
        return {"status": "success", "report": report_record.ai_advice}

    try:
        print(f"🤖 [LLM 호출] {real_session_id}번 방의 마스킹 데이터를 기반으로 생성을 시작합니다...")
        
        ai_report = generate_wrapup_report(host_text=report_record.stt_masked, guest_text="")
        
        report_record.ai_advice = ai_report
        db.commit()
        
        print(f"✅ [DB 저장 완료] AI 어드바이스 저장 완료!")
        return {"status": "success", "report": ai_report}

    except Exception as e:
        db.rollback()
        print(f"🚨 [AI 리포트 생성 실패] 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI 어드바이스 생성 중 오류 발생: {str(e)}")