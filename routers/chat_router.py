from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from models import CoffeeChatReport, ChatSession, get_db, Booking
from .ai_service import generate_wrapup_report 
from .reports import create_and_upload_report_pdf
from .ai_service import generate_wrapup_report, generate_summary
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
    is_failed_report = False
    if report_record.ai_advice and "정보 부족" in report_record.ai_advice:
        is_failed_report = True
    if report_record.summary and "정보 부족" in report_record.summary:
        is_failed_report = True

    # 기존에 분석된 글자가 있고, '정보 부족'이 아니라면 캐시(기존 데이터)를 그대로 씁니다.
    if report_record.ai_advice and not is_failed_report:
        print(f"💾 [캐시 사용] 정상적인 리포트가 존재하여 DB 데이터를 즉시 반환합니다.")
        
        # 글자는 있는데 PDF가 없다면 백그라운드로 PDF만 굽기 시작!
        if not report_record.pdf_url:
            print(f"🛠️ 어드바이스 캐시는 있지만 PDF가 누락되어 백그라운드 생성을 트리거합니다.")
            background_tasks.add_task(create_and_upload_report_pdf, chat_id)
            
        return {
            "ai_advice": report_record.ai_advice,
            "summary": report_record.summary
        }
    
    # 만약 '정보 부족'이라면 아래로 통과시켜서 4단계(AI 재호출)를 실행하게 만듭니다.
    if is_failed_report:
        print("⚠️ [재생성 시작] '정보 부족' 문구가 감지되어 캐시를 무시하고 AI를 다시 호출합니다!")
    # 4단계: AI 어드바이스 생성 및 DB 저장
    try:
        print(f"🤖 [LLM 호출] 데이터를 기반으로 재생성을 시작합니다...")
        
        booking = db.query(Booking).filter(Booking.id == chat_id).first()
        h_name = booking.mentor_name if booking else "멘토"
        g_name = booking.user_name if booking else "멘티"

        # 1. 어드바이스 재생성
        ai_report = generate_wrapup_report(
            host_text=text_to_analyze, 
            guest_text="",
            host_name=h_name,
            guest_name=g_name
        )
        
        # 2. 🌟 대화 요약 재생성 (요약이 망가졌을 경우에만 다시 실행!)
        if is_failed_report:
            print("📝 [요약 재생성] 요약에 '정보 부족'이 감지되어 대화 요약도 다시 생성합니다!")
            
            # (주의: generate_summary 함수명과 넘겨주는 인자는 ai_service.py에 맞게 조절해 주세요!)
            new_summary = generate_summary(text_to_analyze) 
            
            # 새롭게 만든 요약을 DB 레코드에 덮어씁니다.
            report_record.summary = new_summary
        
        # DB에 어드바이스 덮어쓰기
        report_record.ai_advice = ai_report
        db.commit()
        
        print(f"✅ [DB 저장 완료] AI 어드바이스 및 요약 저장 완료!")
        
        background_tasks.add_task(create_and_upload_report_pdf, chat_id)
        
        # ✨ 이제 화면에 방금 새로 만든 똑똑한 요약본이 전달됩니다!
        return {
            "ai_advice": report_record.ai_advice,
            "summary": report_record.summary 
        }

    except Exception as e:
        db.rollback()
        print(f"🚨 [AI 리포트 생성 실패] 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI 어드바이스 생성 중 오류 발생: {str(e)}")