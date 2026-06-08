# routers/stt.py
"""
Azure Speech STT 연동
────────────────────────────────────────────────────────────
흐름:
  1. 프론트가 WebSocket으로 접속 (/ws/stt/{booking_id}/{user_id})
  2. 브라우저 MediaRecorder → PCM(16kHz·16bit·mono) 청크를 서버로 전송
  3. 서버가 Azure Speech SDK로 실시간 인식 → 결과를 같은 방의 두 클라이언트에게 브로드캐스트
  4. 통화 종료 시 전체 STT 텍스트를 ChatSession.stt_text에 저장

환경변수 (.env):
  AZURE_SPEECH_KEY=<your-key>
  AZURE_SPEECH_REGION=koreacentral   # 또는 eastasia 등
"""

import asyncio
import json
import logging
import os
from collections import defaultdict
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

load_dotenv()
logger = logging.getLogger(__name__)
router = APIRouter(tags=["STT"])

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY") 
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "koreacentral")
# Azure SDK는 선택적 import (키가 없는 환경에서도 서버가 뜨도록)
try:
    import azure.cognitiveservices.speech as speechsdk
    SPEECH_AVAILABLE = bool(AZURE_SPEECH_KEY)
except ImportError:
    speechsdk = None
    SPEECH_AVAILABLE = False
    logger.warning("⚠️  azure-cognitiveservices-speech 미설치. STT 비활성화.")


# ──────────────────────────────────────────────
# 방별 STT 상태 관리
# ──────────────────────────────────────────────
class STTRoomState:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}  # uid → ws
        self.transcripts: List[dict] = []             # 전체 대화 누적

    async def broadcast(self, message: dict):
        dead = []
        for uid, ws in self.connections.items():
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(uid)
        for uid in dead:
            del self.connections[uid]


stt_rooms: Dict[str, STTRoomState] = defaultdict(STTRoomState)


# ──────────────────────────────────────────────
# Azure Speech 인식기 생성 헬퍼
# ──────────────────────────────────────────────
def _make_push_stream_recognizer(room_id: str, speaker_name: str, loop: asyncio.AbstractEventLoop):
    """PushAudioInputStream을 이용한 실시간 인식기 반환"""
    if not SPEECH_AVAILABLE:
        return None, None

    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY,
        region=AZURE_SPEECH_REGION,
    )
    speech_config.speech_recognition_language = "ko-KR"
    # 중간 결과도 수신
    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "1500"
    )

    stream = speechsdk.audio.PushAudioInputStream(
        speechsdk.audio.AudioStreamFormat.get_wave_format_pcm(16000, 16, 1)
    )
    audio_config = speechsdk.audio.AudioConfig(stream=stream)
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    room_state = stt_rooms[room_id]

    def on_recognized(evt):
        text = evt.result.text.strip()
        if not text:
            return
        entry = {"speaker": speaker_name, "text": text, "type": "final"}
        room_state.transcripts.append(entry)
        asyncio.run_coroutine_threadsafe(room_state.broadcast(entry), loop)
        logger.info(f"[STT] room={room_id} speaker={speaker_name}: {text}")

    def on_recognizing(evt):
        text = evt.result.text.strip()
        if not text:
            return
        # 중간 결과는 DB 저장 없이 브로드캐스트만
        asyncio.run_coroutine_threadsafe(
            room_state.broadcast({"speaker": speaker_name, "text": text, "type": "interim"}),
            loop,
        )

    recognizer.recognized.connect(on_recognized)
    recognizer.recognizing.connect(on_recognizing)
    recognizer.start_continuous_recognition()

    return recognizer, stream


# ──────────────────────────────────────────────
# STT WebSocket 엔드포인트
# ws://host/ws/stt/{booking_id}/{user_id}/{speaker_name}
# ──────────────────────────────────────────────
@router.websocket("/ws/stt/{booking_id}/{user_id}/{speaker_name}")
async def stt_endpoint(
    websocket: WebSocket,
    booking_id: int,
    user_id: int,
    speaker_name: str,
):
    """
    클라이언트가 보내는 메시지 타입:
      - binary: PCM 오디오 청크 (16kHz·16bit·mono)
      - text JSON {"type": "end_session"}: 통화 종료, DB 저장 요청
    """
    from models import ChatSession, get_db as _get_db  # 순환 import 방지

    room_id = str(booking_id)
    uid = str(user_id)
    room_state = stt_rooms[room_id]

    await websocket.accept()
    room_state.connections[uid] = websocket
    logger.info(f"[STT] 접속 room={room_id} uid={uid} speaker={speaker_name}")

    # Azure 인식기 초기화
    loop = asyncio.get_event_loop()
    recognizer, push_stream = _make_push_stream_recognizer(room_id, speaker_name, loop)

    if not SPEECH_AVAILABLE:
        # STT 불가 환경에서도 더미 응답으로 연결은 유지
        await websocket.send_json({
            "type": "notice",
            "text": "STT 서비스가 설정되지 않았습니다. 텍스트만 수신됩니다.",
        })

    try:
        while True:
            msg = await websocket.receive()

            # 💡 [핵심 추가 포인트] 클라이언트가 연결을 끊으면 즉시 루프 탈출
            if msg.get("type") == "websocket.disconnect":
                logger.info(f"[STT] 클라이언트가 웹소켓 연결을 종료했습니다. (Disconnect 감지)")
                break

            if "bytes" in msg and push_stream:
                if len(msg["bytes"]) > 0:
                    # 너무 자주 찍히면 성능 저하가 올 수 있으니 디버깅 후엔 주석 처리 추천
                    # logger.info(f"🎤 [STT] 오디오 청크 수신: {len(msg['bytes'])} bytes") 
                    push_stream.write(msg["bytes"])

            elif "text" in msg:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "end_session":
                    # ── 세션 종료: STT 결과 DB 저장 ───────────
                    full_text = "\n".join(
                        f"[{t['speaker']}] {t['text']}"
                        for t in room_state.transcripts
                        if t.get("type") == "final"
                    )
                    try:
                        db_gen = _get_db()
                        db: Session = next(db_gen)
                        session = db.query(ChatSession).filter(
                            ChatSession.booking_id == booking_id
                        ).first()
                        if session:
                            session.stt_text = full_text
                            db.commit()
                            logger.info(f"[STT] stt_text DB 저장 완료 booking_id={booking_id}")
                    except Exception as db_err:
                        logger.error(f"[STT] DB 저장 실패: {db_err}")
                    finally:
                        try:
                            next(db_gen)
                        except StopIteration:
                            pass

                    await websocket.send_json({
                        "type": "session_ended",
                        "total_lines": len(room_state.transcripts),
                    })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[STT] 예외 room={room_id} uid={uid}: {e}")
    finally:
        # 인식기 정리
        if recognizer:
            try:
                recognizer.stop_continuous_recognition()
            except Exception:
                pass
        if push_stream:
            try:
                push_stream.close()
            except Exception:
                pass

        if uid in room_state.connections:
            del room_state.connections[uid]
        logger.info(f"[STT] 연결 해제 room={room_id} uid={uid}")


# ──────────────────────────────────────────────
# STT 텍스트 조회 REST API
# GET /api/stt/{booking_id}
# ──────────────────────────────────────────────
@router.get("/api/stt/{booking_id}")
def get_stt_transcript(booking_id: int):
    """현재 진행 중인 방의 STT 내역 반환 (REST 폴링용)"""
    room_id = str(booking_id)
    state = stt_rooms.get(room_id)
    if not state:
        return {"transcripts": []}
    return {"transcripts": [t for t in state.transcripts if t.get("type") == "final"]}