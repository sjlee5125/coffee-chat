import json
import logging
import os
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from routers.pipeline import agent_regex_masking, agent_azure_pii, agent_llm_masking, agent_llm_summary


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

            if data.get("type") != "question":
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