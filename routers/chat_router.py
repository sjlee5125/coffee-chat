from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

# models.py에서 정의한 테이블 객체와 DB 제너레이터 함수를 가져옵니다.
from models import CoffeeChatReport, get_db
# 기존에 사용하시던 AI 서비스 함수를 그대로 유지합니다.
from .ai_service import generate_wrapup_report 

router = APIRouter()

@router.post("/api/wrap-up/{chat_id}")
async def get_wrapup_report(chat_id: int, db: Session = Depends(get_db)):
    print(f"🔄 [AI 랩업 리포트 생성 요청] Chat ID: {chat_id}")
    
    # 1. DB의 public.coffee_chat_reports 테이블에서 현재 chatsession_id와 일치하는 레코드를 찾습니다.
    report_record = db.query(CoffeeChatReport).filter(CoffeeChatReport.chatsession_id == chat_id).first()
    
    # 2. 만약 해당 방의 레코드가 없거나, 아직 알고리즘에 의해 stt_masked가 채워지지 않았다면 에러를 반환합니다.
    if not report_record:
        raise HTTPException(status_code=404, detail="해당 커피챗의 리포트 데이터를 찾을 수 없습니다.")
    
    if not report_record.stt_masked:
        raise HTTPException(status_code=400, detail="마스킹 처리된 대화록(stt_masked)이 아직 준비되지 않았습니다.")
    
    # 3. [비용 절약 최적화] 만약 이미 생성된 어드바이스가 DB에 저장되어 있다면, LLM을 또 돌리지 않고 그대로 반환합니다!
    if report_record.ai_advice:
        print(f"💾 [캐시 사용] 이미 생성된 AI 어드바이스가 존재하여 DB 데이터를 즉시 반환합니다. Chat ID: {chat_id}")
        return {"status": "success", "report": report_record.ai_advice}

    try:
        print(f"🤖 [LLM 호출] {chat_id}번 방의 마스킹된 데이터를 기반으로 AI 어드바이스 생성을 시작합니다...")
        
        # 4. DB에서 꺼내온 실제 마스킹 데이터(report_record.stt_masked)를 LLM 함수에 주입합니다.
        # (기존 generate_wrapup_report 함수가 host와 guest 분리를 원한다면 통째로 넣거나 
        #  그에 맞게 조율할 수 있지만, 현재는 마스킹된 통문을 기반으로 분석하도록 구현합니다.)
        ai_report = generate_wrapup_report(host_text=report_record.stt_masked, guest_text="")
        
        # 5. LLM이 생성한 따끈따끈한 리포트 결과를 DB의 ai_advice 컬럼에 집어넣습니다.
        report_record.ai_advice = ai_report
        
        # 6. DB에 최종 저장(커밋)을 쳐서 안전하게 보관합니다.
        db.commit()
        print(f"✅ [DB 저장 완료] AI 어드바이스가 DB에 성공적으로 기록되었습니다. Chat ID: {chat_id}")
        
        # 7. 프론트엔드가 기대하는 양식 그대로 결과를 반환합니다.
        return {"status": "success", "report": ai_report}

    except Exception as e:
        # 에러가 발생하면 무작정 죽는 게 아니라 원인을 기록하고 안전하게 예외처리합니다.
        db.rollback() # 에러 발생 시 DB 진행사항 복구
        print(f"🚨 [AI 리포트 생성 실패] 에러 내용: {str(e)}")
        return {"status": "error", "message": f"AI 어드바이스 생성 중 오류 발생: {str(e)}"}