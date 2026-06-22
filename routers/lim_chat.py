import json
import logging
import os
from typing import Dict, List, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from models import get_db, ChatSession
# DB 모델 및 의존성
from models import SessionLocal, ChatSession, get_db, Booking, Mentor, CoffeeChatReport

class RecommendQuestionRequest(BaseModel):
    booking_id: int
    stt_text: Optional[str] = ""

load_dotenv()
logger = logging.getLogger(__name__)
router = APIRouter(tags=["LLM Assistant"])

AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-02-15-preview")

try:
    from openai import AzureOpenAI
    
    logger.info(f"LLM KEY 존재 여부: {bool(AZURE_OPENAI_KEY)}")
    logger.info(f"LLM ENDPOINT: {AZURE_OPENAI_ENDPOINT}")
    logger.info(f"LLM DEPLOYMENT: {AZURE_DEPLOYMENT_NAME}")
    
    if all([AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, AZURE_DEPLOYMENT_NAME]):
        llm_client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
        )
        logger.info("✅ Azure OpenAI 클라이언트 초기화 성공!")
    else:
        llm_client = None
        logger.warning("⚠️ Azure OpenAI 환경변수가 누락되어 LLM이 비활성화됩니다.")
        
except Exception as e:
    llm_client = None
    logger.error(f"🚨 Azure OpenAI 초기화 중 에러 발생 (패키지 설치 확인): {e}")

# 방별 대화 히스토리 (LLM 멀티턴용)
llm_histories: Dict[str, List[dict]] = {}

def _build_system_prompt(questions: str) -> str:
    """실시간 가독성을 극대화한 초간결 어시스턴트 프롬프트"""
    questions_text = questions.strip() if questions else "  (질문지 없음)"

    return f"""당신은 커리어 멘토링 중 사용자가 실시간으로 몰래 확인하는 '초간결 기술 사전 어시스턴트'입니다.
사용자가 대화 흐름을 놓치지 않고 3초 안에 읽을 수 있도록 답변을 극단적으로 압축해야 합니다.

[사용자 질문지 참고용]
{questions_text}

역할:
- 멘티가 질문하면 현재 대화 맥락을 바탕으로 구체적인 답변·조언을 제공합니다.
- 멘토에게 다음에 물어볼 만한 추가 질문을 제안할 수 있습니다.
- 대화 중 나온 기술 용어나 개념을 간략하게 설명할 수 있습니다.
- 답변은 간결하고 실용적으로, 3~5문장 내외로 작성합니다.
- 한국어로 답변합니다.

지침 (반드시 엄수):
1. 인사말이나 불필요한 도입부는 절대 쓰지 마십시오. 질문을 받으면 곧바로 핵심 정의나 결론부터 출력합니다.
2. 답변은 무조건 1~2문장(최대 100자 내외)으로 끝내십시오.
3. 명확한 개념 구분이 필요할 때만 핵심 키워드 중심의 짧은 기호(- 또는 숫자)를 사용하되, 최대 2줄을 넘기지 마십시오."""


@router.websocket("/ws/llm/{booking_id}/{user_id}")
async def llm_assistant(websocket: WebSocket, booking_id: int, user_id: int):
    room_id = str(booking_id)
    await websocket.accept()
    logger.info(f"[LLM] 접속 room={room_id} uid={user_id}")

    if room_id not in llm_histories:
        llm_histories[room_id] = []

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            # 추천 질문 요청 처리
            if msg_type == "recommend_questions":
                conversation = data.get("conversation", "")
                preset_questions = data.get("preset_questions", "")

                if not llm_client:
                    default_questions = [
                        "현재 직무에서 가장 중요한 역량은 무엇인가요?",
                        "처음 이 직무를 시작했을 때 어려웠던 점은?",
                        "신입 지원자에게 해주고 싶은 조언이 있으신가요?"
                    ]
                    await websocket.send_json({"type": "recommended_questions", "questions": default_questions})
                    continue

                try:
                    recommend_prompt = f"""멘티가 사전에 준비한 질문 목록:
                    {preset_questions if preset_questions else '없음'}

                    지금까지 나눈 대화 내용:
                    {conversation if conversation else '아직 대화 없음'}

                    위 두 가지를 모두 참고해서 지금 이 순간 멘티가 물어보면 가장 좋을 질문 3개를 추천해주세요.
                    사전 질문 중 아직 안 한 것 위주로, 대화 흐름에 맞게 골라주세요.
                    반드시 JSON 배열로만 응답하세요.
                    예시: ["질문1", "질문2", "질문3"]"""

                    response = llm_client.chat.completions.create(
                        model=AZURE_DEPLOYMENT_NAME,
                        messages=[
                            {"role": "system", "content": "당신은 커피챗 멘토링 어시스턴트입니다. JSON 배열로만 응답하세요."},
                            {"role": "user", "content": recommend_prompt}
                        ],
                        temperature=0.7,
                        max_tokens=300
                    )

                    content = response.choices[0].message.content.strip()
                    questions = json.loads(content)

                    await websocket.send_json({"type": "recommended_questions", "questions": questions})
                    
                    # DB 저장 로직 (flag_modified 적용)
                    session_db = SessionLocal()
                    try:
                        chat_session = session_db.query(ChatSession).filter(ChatSession.booking_id == booking_id).first()
                        if chat_session:
                            existing = chat_session.recommended_questions or []
                            chat_session.recommended_questions = existing + questions
                            flag_modified(chat_session, "recommended_questions")
                            session_db.commit()
                            logger.info(f"[추천질문] DB 저장 완료 booking_id={booking_id}")
                    finally:
                        session_db.close()

                except Exception as e:
                    logger.error(f"[추천질문 생성 실패]: {e}")
                continue

            if msg_type != "question":
                continue

            user_text = data.get("text", "").strip()
            questions = data.get("questions", "")

            if not user_text:
                continue

            if not llm_client:
                await websocket.send_json({"type": "error", "text": "LLM 서비스가 설정되지 않았습니다."})
                continue

            system_prompt = _build_system_prompt(questions)
            history = llm_histories[room_id]
            history.append({"role": "user", "content": user_text})

            if len(history) > 20:
                history = history[-20:]
                llm_histories[room_id] = history

            messages = [{"role": "system", "content": system_prompt}] + history
            full_response = ""
            
            try:
                stream = llm_client.chat.completions.create(
                    model=AZURE_DEPLOYMENT_NAME,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=150,
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        full_response += delta.content
                        await websocket.send_json({"type": "chunk", "text": delta.content})

                history.append({"role": "assistant", "content": full_response})
                await websocket.send_json({"type": "done", "text": full_response})

            except Exception as llm_err:
                logger.error(f"[LLM] Azure 오류: {llm_err}")
                await websocket.send_json({"type": "error", "text": f"AI 응답 중 오류가 발생했습니다: {str(llm_err)}"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[LLM] 예외 room={room_id} uid={user_id}: {e}")
    finally:
        logger.info(f"[LLM] 연결 해제 room={room_id} uid={user_id}")

@router.post("/{chat_id}/generate-summary")
async def generate_summary(chat_id: int, request: Request, db: Session = Depends(get_db)): 
    print(f"🚀 [{chat_id}번 방] 파이프라인 가동! (PDF용 JSON 및 줄글 생성)")

    session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    
    if session and session.stt_text:
        raw_text = session.stt_text
    else:
        raw_text = """Host: 아, 아. 네, 아름 님 안녕하세요..."""  # fallback

    try:
        from routers.pipeline import MaskingEngine, agent_llm_summary
        
        # ✅ 엔진 하나로 전체 파이프라인 — masking_map이 유지됨
        engine = MaskingEngine()
        step0_text = engine.apply_regex(raw_text)
        step1_text = engine.apply_azure_ner(step0_text)

        # LLM 요약 (마스킹된 텍스트로)
        final_json_str = agent_llm_summary(step1_text)
        final_json_str = final_json_str.replace("```json", "").replace("```", "").strip()
        print(f"🔎 masking_map: {engine.masking_map}")
        print(f"🔎 LLM 출력(복구 전) 일부: {final_json_str[:300]}")
        restored_json_str = engine.demask_text(final_json_str)
        print(f"🔎 복구 후 일부: {restored_json_str[:300]}")
        # ✅ 반드시 demask 후 파싱 — 이게 빠져있었던 것

        parsed = json.loads(restored_json_str)

        # 나머지 저장 로직은 그대로...
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

            report = db.query(CoffeeChatReport).filter(
                CoffeeChatReport.chatsession_id == session.id
            ).first()

            if not report:
                # ✅ row 없으면 새로 생성
                report = CoffeeChatReport(
                    chatsession_id=session.id,
                    mentor_id=session.mentor_id,
                    mentee_id=session.user_id,
                )
                db.add(report)
                db.flush()
                print(f"📝 [{chat_id}번 방] CoffeeChatReport 신규 생성")

            # ✅ 있든 없든 무조건 저장
            report.summary     = pretty_text
            report.stt_masked  = step1_text
            report.masking_map = engine.masking_map

            db.commit()
            print(f"🎉 [{chat_id}번 방] DB 저장 완료")

    except Exception as e:
        print(f"🚨 파이프라인 에러 발생: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"요약본 생성 중 서버 에러: {str(e)}")

# ---------------------------------------- HTTP 방식 추천 질문 API ----------------------------------------
@router.post("/recommend-question")
async def recommend_question(request: RecommendQuestionRequest, db: Session = Depends(get_db)):
    print(f" [추천 질문 생성] booking_id={request.booking_id}")
    
    booking = db.query(Booking).filter(Booking.id == request.booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 정보 없음")
    
    mentor = db.query(Mentor).filter(Mentor.id == booking.mentor_id).first()
    mentor_job = mentor.job_title if mentor else "현직자"
    mentee_questions = booking.questions or ""

    system_prompt = """당신은 커피챗 멘토링 어시스턴트입니다.
멘티가 멘토에게 물어볼 수 있는 좋은 질문 3개를 추천해주세요.
반드시 JSON 배열 형태로만 응답하세요.
예시: ["질문1", "질문2", "질문3"]"""

    user_prompt = f"""멘토 직무: {mentor_job}
멘티가 준비한 질문: {mentee_questions}
지금까지 나눈 대화: {request.stt_text or '아직 대화 없음'}

위 내용을 바탕으로 지금 이 순간 멘티가 물어보면 좋을 질문 3개를 추천해주세요."""

    try:
        from routers.ai_service import client, DEPLOYMENT_NAME
        if not client:
            return {"questions": ["멘토님의 커리어 전환 계기가 궁금해요!", "현재 직무에서 가장 중요한 역량은 무엇인가요?", "신입으로서 준비해야 할 것들이 있을까요?"]}
        
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        content = response.choices[0].message.content.strip()
        return {"questions": json.loads(content)}
        
    except Exception as e:
        print(f" [추천 질문 생성 실패]: {e}")
        return {"questions": [
            f"{mentor_job} 직무에서 가장 중요한 역량은 무엇인가요?",
            "처음 이 직무를 시작했을 때 가장 어려웠던 점은 무엇인가요?",
            "신입 지원자에게 해주고 싶은 조언이 있으신가요?"
        ]}