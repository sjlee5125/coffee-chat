import json
import logging
import os
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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


def _build_system_prompt(questions: str) -> str:
    """예약 질문지만 참고하여 시크릿 AI 어시스턴트 프롬프트 생성"""
    questions_text = questions.strip() if questions else "  (질문지 없음)"

    return f"""당신은 커리어 멘토링 커피챗을 실시간으로 보조하는 '나만의 시크릿 AI 어시스턴트'입니다.
사용자(멘티)가 대화 중에 궁금한 기술 용어나 커리어 고민을 당신에게 따로 물어보는 상황입니다.

[사용자가 미리 작성한 커피챗 질문지]
{questions_text}

역할:
- 사용자가 질문한 기술 용어, 개념, 혹은 커리어 관련 질문에 대해 명쾌하게 답변합니다.
- 답변은 사용자가 멘토링 흐름을 놓치지 않고 빠르게 읽을 수 있도록 매우 간결하고 실용적으로, 2~3문장 내외로 핵심만 작성합니다.
- 친절하면서도 전문적인 멘토의 톤앤매너를 유지하며, 한국어로 답변합니다."""


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
                    temperature=0.5,  # 조금 더 정확하고 정제된 답변을 위해 온도를 살짝 낮춤
                    max_tokens=400,   # 짧은 답변 목적이므로 맥스 토큰 최적화
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