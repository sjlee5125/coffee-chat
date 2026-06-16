import json
import logging
import os
from typing import Dict, List, Optional  # 💡 Optional 추가
from models import SessionLocal, ChatSession
from pydantic import BaseModel  # 💡 BaseModel 추가
from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends  # 💡 Depends 추가
from sqlalchemy.orm import Session  # 💡 Session 추가

# 💡 DB 모델 및 의존성 추가 (models 파일에서 가져옴)
from models import get_db, Booking, Mentor

from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary

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
    
    # 💡 디버깅용: 설정값 잘 불러왔는지 터미널에 출력
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

지침 (반드시 엄수):
1. 인사말("안녕하세요", "도와드릴게요")이나 불필요한 도입부("질문하신 ~는")는 절대 쓰지 마십시오. 질문을 받으면 곧바로 핵심 정의나 결론부터 출력합니다.
2. 답변은 무조건 1~2문장(최대 100자 내외)으로 끝내십시오.
3. 명확한 개념 구분이 필요할 때만 핵심 키워드 중심의 짧은 기호(- 또는 숫자)를 사용하되, 최대 2줄을 넘기지 마십시오.
4. 친절한 설명보다는 '치트키 사전'처럼 명쾌하고 실용적인 정보만 제공하십시오."""


@router.websocket("/ws/llm/{booking_id}/{user_id}")
async def llm_assistant(
    websocket: WebSocket,
    booking_id: int,
    user_id: int,
):
    """
    클라이언트 메시지 포맷 (JSON):
      { "type": "question", "text": "질문 내용", "questions": "예약 시 작성한 질문지" }

    서버 응답 포맷 (JSON):
      { "type": "chunk",  "text": "..." }   ← 스트리밍 청크
      { "type": "done",   "text": "전체 응답" }
      { "type": "error",  "text": "오류 메시지" }
    """
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
                    await websocket.send_json({
                        "type": "recommended_questions",
                        "questions": default_questions
                    })
                    session_db = SessionLocal()
                    try:
                        chat_session = session_db.query(ChatSession).filter(
                            ChatSession.booking_id == booking_id
                        ).first()
                        if chat_session:
                            chat_session.recommended_questions = default_questions
                            session_db.commit()
                    finally:
                        session_db.close()
                    continue

                try:
                    recommend_prompt = f"""당신은 커피챗 멘토링 어시스턴트입니다.

                    멘티가 사전에 작성한 질문 목록:
                    {preset_questions if preset_questions else '없음'}

                    지금까지 나눈 실제 대화 내용:
                    {conversation if conversation else '아직 대화 없음'}

                    [중요 지침]
                    1. 사전 질문 목록을 그대로 복사하지 마세요.
                    2. 대화 내용을 분석해서 사전 질문 중 아직 다루지 않은 주제를 찾으세요.
                    3. 대화 흐름에 자연스럽게 이어지는 새로운 질문 3개를 직접 작성하세요.
                    4. 사전 질문과 똑같은 문장은 절대 사용하지 마세요. 표현을 다르게 바꾸거나 더 구체적으로 발전시키세요.
                    5. 대화가 아직 없으면 사전 질문을 참고해서 대화를 시작할 수 있는 질문을 만드세요.

                    반드시 JSON 배열 형태로만 응답하세요.
                    예시: ["질문1", "질문2", "질문3"]"""

                    response = llm_client.chat.completions.create(
                        model=AZURE_DEPLOYMENT_NAME,
                        messages=[
                            {"role": "system", "content": "당신은 커피챗 멘토링 어시스턴트입니다. 절대 사전 질문을 그대로 반복하지 마세요. 반드시 새롭게 작성한 질문만 JSON 배열로 응답하세요."},
                            {"role": "user", "content": recommend_prompt}
                        ],
                        temperature=0.7,
                        max_tokens=300
                    )

                    import json as json_module
                    content = response.choices[0].message.content.strip()
                    questions = json_module.loads(content)

                    await websocket.send_json({
                        "type": "recommended_questions",
                        "questions": questions
                    })
                    session_db = SessionLocal()
                    try:
                        chat_session = session_db.query(ChatSession).filter(
                            ChatSession.booking_id == booking_id
                        ).first()
                        if chat_session:
                            existing = chat_session.recommended_questions or []
                            chat_session.recommended_questions = existing + questions
                            from sqlalchemy.orm.attributes import flag_modified
                            flag_modified(chat_session, "recommended_questions")
                            session_db.commit()
                            logger.info(f"[추천질문] DB 저장 완료 booking_id={booking_id}")
                    finally:
                        session_db.close()

                except Exception as e:
                    default_questions = [
                        "현재 직무에서 가장 중요한 역량은 무엇인가요?",
                        "처음 이 직무를 시작했을 때 어려웠던 점은?",
                        "신입 지원자에게 해주고 싶은 조언이 있으신가요?"
                    ]
                    await websocket.send_json({
                        "type": "recommended_questions",
                        "questions": default_questions
                    })
                    session_db = SessionLocal()
                    try:
                        chat_session = session_db.query(ChatSession).filter(
                            ChatSession.booking_id == booking_id
                        ).first()
                        if chat_session:
                            chat_session.recommended_questions = default_questions
                            session_db.commit()
                    finally:
                        session_db.close()
                continue

            if msg_type != "question":
                continue

            user_text = data.get("text", "").strip()
            questions = data.get("questions", "")

            if not user_text:
                continue

            if not llm_client:
                await websocket.send_json({
                    "type": "error",
                    "text": "LLM 서비스가 설정되지 않았습니다."
                })
                continue

            # 전송받은 질문지를 기반으로 시스템 프롬프트 빌드 (STT 의존성 완전 제거)
            system_prompt = _build_system_prompt(questions)

            # 히스토리에 사용자 메시지 추가
            history = llm_histories[room_id]
            history.append({"role": "user", "content": user_text})

            # 토큰 절약: 히스토리 최대 10턴(20개 메시지) 유지
            if len(history) > 20:
                history = history[-20:]
                llm_histories[room_id] = history

            messages = [{"role": "system", "content": system_prompt}] + history

            # ── 스트리밍 응답 ──────────────────────────
            full_response = ""
            try:
                stream = llm_client.chat.completions.create(
                    model=AZURE_DEPLOYMENT_NAME,
                    messages=messages,
                    temperature=0.3,  # 온도를 0.3으로 더 낮춰서 헛소리 없이 정답만 딱 말하도록 변경
                    max_tokens=150,   # 최대 글자 수 한도를 150토큰 내외로 압축
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        full_response += delta.content
                        await websocket.send_json({
                            "type": "chunk",
                            "text": delta.content,
                        })

                # 히스토리에 어시스턴트 응답 추가
                history.append({"role": "assistant", "content": full_response})

                await websocket.send_json({
                    "type": "done",
                    "text": full_response,
                })
                logger.info(f"[LLM] 응답 완료 room={room_id} ({len(full_response)}자)")

            except Exception as llm_err:
                logger.error(f"[LLM] Azure 오류: {llm_err}")
                await websocket.send_json({
                    "type": "error",
                    "text": f"AI 응답 중 오류가 발생했습니다: {str(llm_err)}"
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[LLM] 예외 room={room_id} uid={user_id}: {e}")
    finally:
        logger.info(f"[LLM] 연결 해제 room={room_id} uid={user_id}")


# ==========================================
# 🚀 프론트에서 [종료] 버튼 누를 때 실행되는 AI 요약본 생성 API
# ==========================================
@router.post("/{chat_id}/generate-summary")
async def generate_summary(chat_id: int):
    print(f"🚀 [{chat_id}번 방] 종료 버튼 클릭 감지! 요약본 생성 파이프라인 시작...")

    # 1. 테스트용 가짜 대화 데이터
    raw_text = """
    Host: 안녕하세요 이다은 님, 한국대학교 졸업하시고 스타브릿지 엔터테인먼트에 입사하셨다고 들었어요. 연락처는 010-1234-5678 맞으시죠?
    Guest: 네 맞습니다. 제 개인 메일 daeun.lee@gmail.com 로도 자료 부탁드릴게요. 연봉 8천만 원 받기로 했습니다.
    """

    try:
        from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary
        import json
        
        # 2. 초고속 보안 필터링 & 요약 파이프라인 가동!
        step0_text = agent_regex_masking(raw_text)
        step1_text = agent_azure_pii(step0_text)
        step2_text = agent_llm_masking(step1_text)
        final_json_str = agent_llm_summary(step2_text)

        parsed_json = json.loads(final_json_str)

        print(f"✅ [{chat_id}번 방] 요약본 생성 완료!")
        
        return {"message": "요약본 생성 성공", "data": parsed_json}

    except Exception as e:
        print(f"🚨 파이프라인 에러 발생: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"요약본 생성 중 서버 에러: {str(e)}")


# ----------------------------------------ai추천질문----------------------------------------
@router.post("/recommend-question")
async def recommend_question(request: RecommendQuestionRequest, db: Session = Depends(get_db)):
    print(f" [추천 질문 생성] booking_id={request.booking_id}")
    
    # 1. 예약 정보 가져오기 (멘티 질문지, 멘토 직무)
    booking = db.query(Booking).filter(Booking.id == request.booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="예약 정보 없음")
    
    mentor = db.query(Mentor).filter(Mentor.id == booking.mentor_id).first()
    mentor_job = mentor.job_title if mentor else "현직자"
    mentee_questions = booking.questions or ""

    # 2. 프롬프트 구성
    system_prompt = """당신은 커피챗 멘토링 어시스턴트입니다.
멘티가 멘토에게 물어볼 수 있는 좋은 질문 3개를 추천해주세요.
반드시 JSON 배열 형태로만 응답하세요.
예시: ["질문1", "질문2", "질문3"]"""

    user_prompt = f"""멘토 직무: {mentor_job}
멘티가 준비한 질문: {mentee_questions}
지금까지 나눈 대화: {request.stt_text or '아직 대화 없음'}

위 내용을 바탕으로 지금 이 순간 멘티가 물어보면 좋을 질문 3개를 추천해주세요."""

    # 3. Azure OpenAI 호출
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
        
        import json
        content = response.choices[0].message.content.strip()
        questions = json.loads(content)
        return {"questions": questions}
        
    except Exception as e:
        print(f" [추천 질문 생성 실패]: {e}")
        # 기본 질문 반환
        return {"questions": [
            f"{mentor_job} 직무에서 가장 중요한 역량은 무엇인가요?",
            "처음 이 직무를 시작했을 때 가장 어려웠던 점은 무엇인가요?",
            "신입 지원자에게 해주고 싶은 조언이 있으신가요?"
        ]}