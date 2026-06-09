# routers/llm_chat.py
"""
LLM 어시스턴트 WebSocket
────────────────────────────────────────────────────────────
흐름:
  1. 클라이언트가 ws://host/ws/llm/{booking_id}/{user_id} 접속
  2. 사용자가 질문 텍스트 전송
  3. 서버가 해당 방의 STT 대화 맥락 + 예약 질문지를 시스템 프롬프트에 주입
  4. Azure OpenAI로 스트리밍 응답 → 청크 단위로 클라이언트에 전송

환경변수: 기존 ai.py와 동일 (AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT 등)
"""

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
    llm_client = AzureOpenAI(
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
    ) if all([AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, AZURE_DEPLOYMENT_NAME]) else None
except Exception:
    llm_client = None

# 방별 대화 히스토리 (LLM 멀티턴용)
llm_histories: Dict[str, List[dict]] = {}


def _build_system_prompt(stt_transcripts: List[dict], questions: str) -> str:
    """STT 맥락과 질문지를 포함한 시스템 프롬프트 생성"""
    recent_stt = "\n".join(
        f"  [{t['speaker']}] {t['text']}"
        for t in stt_transcripts[-20:]  # 최근 20문장만 주입 (토큰 절약)
        if t.get("type") == "final"
    ) or "  (아직 대화 내용이 없습니다)"

    questions_text = questions.strip() if questions else "  (질문지 없음)"

    return f"""당신은 커리어 멘토링 커피챗을 실시간으로 보조하는 AI 어시스턴트입니다.

[현재 대화 맥락 (STT 인식 결과)]
{recent_stt}

[멘티가 준비한 질문지]
{questions_text}

역할:
- 멘티가 질문하면 현재 대화 맥락을 바탕으로 구체적인 답변·조언을 제공합니다.
- 멘토에게 다음에 물어볼 만한 추가 질문을 제안할 수 있습니다.
- 대화 중 나온 기술 용어나 개념을 간략하게 설명할 수 있습니다.
- 답변은 간결하고 실용적으로, 3~5문장 내외로 작성합니다.
- 한국어로 답변합니다."""


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
    from routers.stt import stt_rooms  # 순환 import 방지

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

            # STT 맥락 가져오기
            stt_state = stt_rooms.get(room_id)
            transcripts = stt_state.transcripts if stt_state else []

            system_prompt = _build_system_prompt(transcripts, questions)

            # 히스토리에 사용자 메시지 추가
            history = llm_histories[room_id]
            history.append({"role": "user", "content": user_text})

            # 토큰 절약: 히스토리 최대 10턴 유지
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
                    temperature=0.7,
                    max_tokens=500,
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