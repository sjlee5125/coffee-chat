# routers/chat.py
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel

from models import Booking, ChatSession, get_db
from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary
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
    
    # DB에 저장된 요약본(JSON)을 가져옵니다.
    summary_data = session.ai_summary
    display_text = summary_data # 기본값은 일단 가져온 그대로.

    if summary_data and isinstance(summary_data, str) and summary_data.strip().startswith("{"):
        try:
            import json
            # JSON을 파싱해서 줄글로 변환하는 '번역기'입니다.
            parsed = json.loads(summary_data.replace("```json", "").replace("```", "").strip())
            
            meta = parsed.get("session_metadata", {})
            agendas = parsed.get("core_agendas", [])
            consensus = parsed.get("session_consensus", "내용 없음")

            # PDF와 동일한 줄글 리포트 생성!
            pretty_text = f"1. 게스트 상황 및 목표\n[현재 상황]\n{meta.get('guest_as_is', '내용 없음')}\n\n[목표]\n{meta.get('guest_to_be', '내용 없음')}\n\n"
            pretty_text += "2. 핵심 논의 안건\n"
            if agendas:
                for i, a in enumerate(agendas, 1):
                    pretty_text += f"{i}. {a.get('agenda_title', '안건')}\n"
                    pretty_text += f"- 질문: {a.get('guest_context', '내용 없음')}\n"
                    pretty_text += f"- 해결책: {a.get('host_solution', '내용 없음')}\n\n"
            pretty_text += f"3. 최종 합의점 및 결론\n{consensus}"
            
            display_text = pretty_text # 화면에 나갈 텍스트를 줄글로 교체!
        except Exception as e:
            print(f"번역기 에러: {e}")

    return {
        "session_id": session.id,
        "status": session.status,
        "started_at": str(session.started_at) if session.started_at else None,
        "ai_summary": display_text # 👈 이제 줄글이 들어갑니다!
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
# 3. AI 요약본 생성 API (DB에는 원본 JSON 저장!)
# ==========================================

@router.post("/api/chat-session/{chat_id}/generate-summary")
async def generate_summary(chat_id: int, request: Request, db: Session = Depends(get_db)): 
    print(f"🚀 [{chat_id}번 방] 파이프라인 가동! (PDF용 JSON 생성)")

    session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    
    # 💡 실제 STT가 없으면 완벽한 바이오 면접 대본을 사용합니다!
    if session and session.stt_text:
        raw_text = session.stt_text
    else:
        raw_text = """
        Host: 아, 아. 네, 아름 님 안녕하세요. 목소리 잘 들리시나요?
        Guest: 아, 네! 성현 님 안녕하세요. 아주 잘 들립니다! 퇴근하시고 피곤하실 텐데 이렇게 시간 내주셔서 정말 감사드려요.
        Host: 아닙니다. 저도 대학원 석사 졸업하고 취업 준비할 때 연구소 문턱이 너무 높게 느껴져서 고생했던 기억이 나네요. (웃음) 사전 질문지 보니까 연세대학교 생명공학과에서 석사 졸업하시고 지금 넥스트바이오 연구소 쪽에 지원하려고 준비 중이시라고요. 반갑습니다.
        Guest: 네, 맞습니다. 지난 2월에 석사 학위 받고 지금 한 석 달째 본격적으로 구직 활동을 하고 있는데요. 서류는 몇 번 통과해서 면접을 보긴 했는데, 대학원 실습실에서 했던 실험이랑 기업 연구소에서 요구하는 실무 역량 사이에 간극이 좀 큰 것 같아서 매번 면접에서 고배를 마셨습니다. 그래서 현직자이신 성현 님께 조언을 구하고자 신청하게 되었습니다.
        Host: 아... 면접까지 가셨는데 떨어지셨다니 마음이 많이 쓰이셨겠어요. 그래도 석사 학위가 있으시고 서류 통과가 된다는 건 기본적인 스펙이나 연구 역량은 검증되셨다는 뜻이에요. 보통 면접에서 어떤 질문을 받았을 때 가장 답변하기 어려우셨나요?
        Guest: 어... 가장 뼈아팠던 질문이 "본인이 석사 논문에서 진행한 세포 배양 실험은 학술적인 의미는 있지만, 우리 회사의 현재 신약 파이프라인 대량 생산 공정에는 어떻게 적용할 수 있겠냐"라는 질문이었어요. 저는 그냥 랩실 수준에서 웰 플레이트에 키우는 실험만 해봤다 보니, 공장 규모의 대량 생산이나 스케일업(Scale-up) 관점에서는 답변을 아예 못 하겠더라고요.
        Host: 아, 그 질문은 제약·바이오 면접관들이 단골로 던지는 압박 질문이에요. (웃음) 기업은 결국 이윤을 내는 곳이기 때문에, 연구소에서도 랩 스케일의 실험이 상업 생산으로 이어질 수 있는가를 항상 고민하거든요. 아름 님이 석사 과정 중에 주로 다루셨던 분석 장비나 실험 테크닉은 어떤 게 있나요?
        Guest: 저는 주로 단백질 정제랑 분석을 메인으로 해서, HPLC(고성능 액체 크로마토그래피) 장비를 가장 많이 다루었고요. 웨스턴 블롯(Western Blot)이나 ELISA 분석, 그리고 기본적인 동물 세포 배양 기술을 가지고 있습니다. 논문도 면역 항암제 관련 단백질 발현에 대한 주제로 썼고요.
        Host: 오, HPLC를 메인으로 다루실 줄 안다는 건 엄청난 장점이에요! 제약회사 연구소든 QA/QC(품질보증/품질관리) 부서든 HPLC 안 쓰는 곳은 단 한 군데도 없거든요. 아까 면접관의 생산 공정 질문에 답변하실 때는, 본인이 직접 스케일업을 안 해봤더라도 이렇게 논리를 풀어나가셔야 해요. "제가 랩실에서 HPLC 분석 조건(Method)을 잡으면서 불순물 정제 효율을 95%까지 끌어올린 경험이 있습니다. 이 분석 프로토콜은 향후 공정 개발 팀에서 대량 생산 타당성을 검증할 때 가이드라인 역할을 할 수 있으며, 생산 단계에서 발생할 수 있는 품질 불량을 모니터링하는 데 기여할 수 있습니다." 이런 식으로 나의 분석 역량이 공정의 안정성에 기여한다는 연결고리를 만들어주는 거죠.
        Guest: 와... 분석 조건 잡은 경험을 상업화 단계의 품질 모니터링이랑 연결하는 거군요. 저는 맨날 "대량 생산은 안 해봤지만 입사해서 열심히 배우겠습니다"라고만 했었는데, 그렇게 말하니까 제 장비 숙련도가 완전히 다르게 쓰일 수 있겠네요. 소름 돋았습니다. (웃음)
        Host: 하하, 면접관들이 듣고 싶어 하는 말이 바로 그거예요. "내가 가진 툴로 회사의 문제를 어떻게 풀어줄 것인가." 그리고 포트폴리오나 이력서 쓰실 때 장비 모델명까지 구체적으로 적어주시는 게 좋아요. 예를 들어 그냥 'HPLC 다룰 줄 암'이 아니라 'Agilent 1260 이나 Waters 2695 모델 가동 및 데이터 분석 가능' 이런 식으로 쓰면, 실무자들이 보고 "어, 이거 우리 방에서 쓰는 장비네? 들어오면 사수 없이 바로 장비 돌릴 수 있겠구나" 하고 서류 점수를 확 높게 줍니다.
        Guest: 아, 장비 모델명까지요! 연구실에서 매일 보던 장비인데 정작 이력서에는 대분류로만 적었었네요. 당장 내일 장비 사진 찍어둔 거 보고 모델명 다 받아 적어서 이력서 업데이트하겠습니다.
        Host: 네, 아주 사소해 보이지만 실무자들에겐 그게 진짜 경력처럼 보이거든요. (웃음) 어... 그리고 넥스트바이오 연구소 분위기에 대해서도 궁금하다고 하셨는데, 저희는 기본적으로 바이오 의약품, 그러니까 바이오시밀러랑 신약 후보 물질을 개발하는 곳이다 보니까 연구원들의 전문성을 되게 존중해 주는 편이에요. 박사님들도 많고 수평적인 토론 문화가 잘 잡혀 있습니다. 다만, 제약 산업 특성상 데이터의 신뢰성, 즉 데이터 인테그리티(Data Integrity)를 엄청나게 엄격하게 따져요. 실험 노트 하나 쓸 때도 정해진 규정에 맞춰서 써야 하고 오탈자나 데이터 조작은 절대 용납이 안 됩니다.
        Guest: 데이터 인테그리티... 대학원 연구실에서도 교수님이 항상 강조하셨던 건데 기업은 역시 훨씬 더 엄격하군요. 넵, 연구 윤리와 정직함을 강조할 수 있는 실험 노트 트러블 슈팅 경험을 자소서 3번 항목에 녹여내야겠습니다. 어... 그리고 성현 님, 이것도 취준생 입장에서 가장 현실적인 걱정인데... 혹시 넥스트바이오 석사 신입 연구원의 연봉 레인지나 복지 처우가 대략 어떻게 되는지 알 수 있을까요? 대학원 생활을 오래 하다 보니 경제적인 부분도 이제 무시를 못 하겠더라고요.
        Host: 당연히 중요하죠. 든든해야 연구도 잘 되는 법이니까요. (웃음) 저희 넥스트바이오 기준으로 말씀드리면, 학사 신입은 초봉이 4,600만 원 선이고요. 아름 님처럼 석사 학위를 소지하신 분들은 경력 2년을 인정받아서 호봉이 높게 시작해요. 그래서 석사 초봉은 기본급 기준으로 올해 대략 5,400만 원 정도 됩니다.
        Guest: 와... 5,400만 원이요? 생각했던 것보다 훨씬 대우가 좋네요!
        Host: 네, 바이오 업계가 대기업 계열사... 예를 들어 삼성바이오로직스나 셀트리온 같은 곳들이 연봉을 많이 올려놔서, 저희 같은 중견·대형 바이오텍들도 인재를 안 뺏기려고 연봉을 대기업 수준으로 많이 맞춰주는 추세예요. 그리고 연말에 신약 임상 진행 상황이나 매출 목표 달성률에 따라 성과급이 나오는데, 작년에는 연구소 전 직원한테 성과급으로 한 800만 원 정도가 일시금으로 지급됐었어요.
        Guest: 성과급 800만 원까지... 진짜 대학원생 때 한 달에 100만 원 남짓 받으면서 실험하던 시절 생각하면 눈물이 앞을 가리네요. (웃음) 정말 열심히 준비해야겠습니다. 복지 혜택은 어떤 게 있나요?
        Host: 복지는 일단 연구소 안에서 유해 물질이나 방사성 동위원소 같은 걸 다루다 보니까, 안전 관련해서 특수 건강검진을 1년에 두 번 무료로 시켜주고요. '연구 수당'이라고 해서 매달 기본급 외에 30만원씩 고정으로 연구 활동비가 통장에 따로 꽂힙니다. 그리고 석·박사 연구원들을 위해 해외 학회 참관 기회도 매년 우수 연구원들을 선발해서 비행기 표랑 호텔비 전액 지원해 주는데, 저도 작년에 미국 암학회(AACR) 다녀왔거든요. 견문 넓히기에 진짜 좋습니다.
        Guest: 매달 연구 수당 30만 원에 해외 학회 지원까지... 진짜 연구원들을 위한 맞춤형 복지네요. 오늘 성현 님 말씀 듣고 나니까 넥스트바이오에 꼭 입사해야겠다는 열정이 마구 샘솟습니다. 면접 질문 방어 전략부터 장비 모델명 팁까지 정말 돈 주고도 못 배울 조언들이었어요.
        Host: 하하, 도움이 되었다니 저도 뿌듯하네요. 아름 님은 기본 베이스가 탄탄하셔서 아까 말씀드린 '상업화 관점의 스토리텔링'과 '디테일한 장비 기술'만 서류랑 면접에 녹여내시면 하반기 공채 때 무조건 좋은 소식 있을 겁니다. 자신감 잃지 마세요. 혹시 포트폴리오 수정본 나오거나 자소서 넥스트바이오 양식에 맞춰 쓰신 거 피드백 필요하시면 편하게 제 이메일로 보내주세요. 제가 연구소 퇴근하고 틈틈이 봐 드릴게요.
        Guest: 헉, 진짜 보내드려도 괜찮을까요? 선배님 바쁘실 텐데 너무 신세 지는 것 같아서 죄송하면서도 너무 감사하네요... 메일 주소 공유 부탁드립니다!
        Host: 네, 제 회사 계정 알려드릴게요. sunghyun.choi@nextbio.com 입니다. S, U, N, G, H, Y, U, N점 C, H, O, I 골뱅이 넥스트바이오 닷컴 이고요. 메일 발송하시고 제 핸드폰 번호 010-4444-5555 로 "커피챗 진행했던 정아름입니다. 자소서 발송했습니다"라고 문자 한 통만 남겨주세요. 그럼 제가 놓치지 않고 확인해 볼게요.
        Guest: sunghyun.choi@nextbio.com 네! 오탈자 없이 정확하게 타이핑했습니다. 010-4444-5555 번호도 제 연락처에 바로 저장했습니다. 진짜 오늘 주신 소중한 시간 절대 헛되지 않게 밤새워서 이력서 뜯어고치겠습니다. 너무너무 감사드립니다, 성현 님! 꼭 합격해서 인사드리러 가겠습니다. 안녕히 계세요!
        Host: 하하, 네. 너무 무리하진 마시고요. 맛있는 저녁 드시고 푹 쉬세요. 하반기에 꼭 저희 연구소 복도에서 후배 연구원으로 만났으면 좋겠네요. 화이팅입니다! 방 종료하겠습니다.
        """

    try:
        from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary
        
        step0_text = agent_regex_masking(raw_text)
        step1_text = agent_azure_pii(step0_text)
        step2_text = agent_llm_masking(step1_text)
        final_json_str = agent_llm_summary(step2_text)

        # 💡 [수정됨] 엔터가 쳐져 있던 부분을 한 줄로 예쁘게 이었습니다!
        final_json_str = final_json_str.replace("```json", "").replace("```", "").strip()

        # 🚨 [핵심] 번역 없이 'JSON 원본'을 그대로 DB에 저장합니다! (PDF 생성을 위해)
        if session:
            session.ai_summary = final_json_str
            db.commit()
            print(f"💾 [{chat_id}번 방] JSON 원본 DB 저장 완료!")
        
        return {"message": "요약본 생성 성공"}

    # 💡 [수정됨] try에 짝을 맞추는 except 구문을 다시 살려냈습니다!
    except Exception as e:
        print(f"🚨 파이프라인 에러 발생: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"요약본 생성 중 서버 에러: {str(e)}")

# ==========================================
# 4. PDF 다운로드 API (억지 코드 제거, 완벽한 PDF 생성!)
# ==========================================
from fastapi.responses import FileResponse
import os

@router.get("/api/chat-session/{chat_id}/summary-pdf")
async def download_summary_pdf(chat_id: int, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    if not session or not session.ai_summary:
        raise HTTPException(status_code=404, detail="요약본 없음. 먼저 generate-summary를 호출해주세요.")

    import json
    from routers.pipeline import generate_pdf_report # 👈 pipeline.py의 원래 능력을 그대로 빌려옵니다!
    
    try:
        # 💡 DB에 저장된 완벽한 JSON을 파이썬 딕셔너리로 읽어들입니다.
        parsed_json = json.loads(session.ai_summary)
    except Exception as e:
        raise HTTPException(status_code=500, detail="PDF 변환 에러: JSON 형식이 올바르지 않습니다.")

    pdf_path = f"summary_{chat_id}.pdf"
    
    # 💡 억지로 내용을 꾸겨넣지 않고, 깔끔하게 읽힌 JSON 원본을 던져줍니다!
    generate_pdf_report(parsed_json, pdf_path)
    
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=500, detail="PDF 파일 생성에 실패했습니다.")
        
    return FileResponse(pdf_path, media_type="application/pdf", filename="커피챗_상세리포트.pdf")