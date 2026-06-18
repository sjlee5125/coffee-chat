from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from models import CoffeeChatReport, ChatSession, get_db
from .ai_service import generate_wrapup_report 
from .reports import create_and_upload_report_pdf

router = APIRouter()

@router.post("/api/wrap-up/{chat_id}")
async def get_wrapup_report(chat_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    print(f"🔄 [AI 랩업 리포트 생성 요청] 넘어온 URL 번호(booking_id): {chat_id}")
    
    # 1단계: booking_id로 진짜 세션 찾기
    chat_session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    if not chat_session:
        raise HTTPException(status_code=404, detail="해당 예약 번호와 연결된 채팅 세션을 찾을 수 없습니다.")
    
    real_session_id = chat_session.id
    print(f"🔍 진짜 chatsession_id를 찾았습니다: {real_session_id}")
    
    # 2단계: 리포트 레코드 가져오기
    report_record = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == real_session_id).first()
    if not report_record:
        raise HTTPException(status_code=404, detail="해당 커피챗의 리포트 데이터를 찾을 수 없습니다.")
    
    # 💡 [안전장치] 마스킹 데이터가 없으면 원본 텍스트라도 사용하도록 롤백 구조 생성
    text_to_analyze = report_record.stt_masked if report_record.stt_masked else chat_session.stt_text
    if not text_to_analyze:
        text_to_analyze = "이 대화는 텍스트 기록이 없습니다."

    # 3단계: 캐시 데이터가 이미 있다면 즉시 반환 (+ PDF 누락 시 백그라운드 생성 트리거)
    if report_record.ai_advice:
        print(f"💾 [캐시 사용] 이미 생성된 AI 어드바이스가 존재하여 DB 데이터를 즉시 반환합니다.")
        
        # 🌟 [수정 1] 이미 분석 글자는 DB에 있지만, PDF 파일이 없다면 백그라운드로 즉시 생성 시작!
        if not report_record.pdf_url:
            print(f"🛠️ 어드바이스 캐시는 있지만 PDF가 누락되어 백그라운드 생성을 트리거합니다.")
            background_tasks.add_task(create_and_upload_report_pdf, chat_id)
            
        return {
            "ai_advice": report_record.ai_advice,
            "summary": report_record.summary
        }

    # 4단계: AI 어드바이스 생성 및 DB 저장
    try:
        print(f"🤖 [LLM 호출] 데이터를 기반으로 어드바이스 생성을 시작합니다...")
        
        ai_report = generate_wrapup_report(host_text=text_to_analyze, guest_text="")
        
        # DB에 저장
        report_record.ai_advice = ai_report
        db.commit()
        
        print(f"✅ [DB 저장 완료] AI 어드바이스 저장 완료!")
        
        # 🌟 [수정 2] 응답을 가로막던 동기식 create_and_upload_report_pdf(db, chat_id) 호출은 과감히 삭제합니다!
        # 오직 background_tasks를 통해서만 조용히 일하게 만들어 유저에게 0.1초 만에 완료 JSON을 보냅니다.
        background_tasks.add_task(create_and_upload_report_pdf, chat_id)
        
        # ✨ 프론트엔드가 요구하는 JSON 구조로 똑같이 맞춰서 리턴!
        return {
            "ai_advice": ai_report,
            "summary": report_record.summary
        }

    except Exception as e:
        db.rollback()
        print(f"🚨 [AI 리포트 생성 실패] 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI 어드바이스 생성 중 오류 발생: {str(e)}")