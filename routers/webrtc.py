# routers/webrtc.py
"""
WebRTC 시그널링 서버
────────────────────────────────────────────────────────────
역할: 브라우저끼리 직접 P2P 연결을 맺기 전에 필요한
      offer / answer / ICE candidate 메시지를 중계합니다.
      미디어(영상·음성)는 이 서버를 통하지 않고 브라우저끼리 직접 흐릅니다.

방 구조: room_id = booking_id (예: "42")
         한 방에 최대 2명 (멘토 + 멘티)
"""

import json
import logging
from typing import Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
# 💡 여기에 방금 복사한 3줄을 추가하세요!
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Booking, Mentor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebRTC Signaling"])


# ──────────────────────────────────────────────
# 방(Room) 관리
# ──────────────────────────────────────────────
class SignalingRoom:
    """booking_id 1개 = 방 1개, 최대 2명"""

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.peers: Dict[str, WebSocket] = {}   # { user_id_str: websocket }

    @property
    def is_full(self) -> bool:
        return len(self.peers) >= 2

    @property
    def peer_ids(self) -> List[str]:
        return list(self.peers.keys())

    async def broadcast_except(self, sender_id: str, message: dict):
        """발신자를 제외한 상대방에게 메시지 전송"""
        for uid, ws in self.peers.items():
            if uid != sender_id:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.warning(f"[시그널링] 전송 실패 uid={uid}: {e}")


class RoomManager:
    def __init__(self):
        self._rooms: Dict[str, SignalingRoom] = {}

    def get_or_create(self, room_id: str) -> SignalingRoom:
        if room_id not in self._rooms:
            self._rooms[room_id] = SignalingRoom(room_id)
        return self._rooms[room_id]

    def remove_peer(self, room_id: str, user_id: str):
        room = self._rooms.get(room_id)
        if room and user_id in room.peers:
            del room.peers[user_id]
            logger.info(f"[시그널링] 퇴장 room={room_id} uid={user_id} (남은 인원: {len(room.peers)})")
            # 방이 비면 정리
            if not room.peers:
                del self._rooms[room_id]
                logger.info(f"[시그널링] 방 삭제 room={room_id}")


room_manager = RoomManager()


# ──────────────────────────────────────────────
# WebSocket 엔드포인트
# ws://host/ws/webrtc/{booking_id}/{user_id}
# ──────────────────────────────────────────────
@router.websocket("/ws/webrtc/{booking_id}/{user_id}")
async def webrtc_signaling(
    websocket: WebSocket,
    booking_id: int,
    user_id: int,
):
    room_id = str(booking_id)
    uid = str(user_id)

    room = room_manager.get_or_create(room_id)

    # 방이 꽉 찼으면 거절
    if room.is_full and uid not in room.peers:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "방이 가득 찼습니다."})
        await websocket.close()
        return

    await websocket.accept()
    room.peers[uid] = websocket
    logger.info(f"[시그널링] 입장 room={room_id} uid={uid} (현재 {len(room.peers)}명)")
    db: Session = SessionLocal() # DB 세션 수동 열기
    try:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if booking:
            # 입장한 유저가 멘토인지 멘티인지 구분해서 도장 찍기
            mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
            if mentor and booking.mentor_id == mentor.id:
                booking.is_mentor_entered = True
            elif booking.user_id == user_id:
                booking.is_mentee_entered = True
                
            db.commit()
            logger.info(f"✅ DB 기록 완료: 방 {booking_id}번 - 유저 {user_id} 입장")
    except Exception as e:
        logger.error(f"🚨 DB 입장 기록 실패: {e}")
    finally:
        db.close() # DB 세션 수동 닫기

    # 상대방에게 입장 알림 → 상대가 먼저 들어와 있으면 offer를 만들게 함
    await room.broadcast_except(uid, {
        "type": "peer_joined",
        "from": uid,
        "peer_count": len(room.peers),
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            # ── 시그널링 메시지 중계 ──────────────────────
            # offer, answer, ice-candidate 를 상대방에게 그대로 포워딩
            if msg_type in ("offer", "answer", "ice-candidate"):
                msg["from"] = uid          # 발신자 ID 주입
                await room.broadcast_except(uid, msg)
                logger.debug(f"[시그널링] {msg_type} 중계 room={room_id} from={uid}")

            # ── 통화 종료 ─────────────────────────────────
            elif msg_type == "hang-up":
                await room.broadcast_except(uid, {"type": "hang-up", "from": uid})
                logger.info(f"[시그널링] hang-up room={room_id} from={uid}")

            # ── 기타 (채팅·커스텀 이벤트) ────────────────
            else:
                await room.broadcast_except(uid, msg)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[시그널링] 예외 room={room_id} uid={uid}: {e}")
    finally:
        room_manager.remove_peer(room_id, uid)
        # 상대방에게 연결 해제 알림
        remaining_room = room_manager._rooms.get(room_id)
        if remaining_room:
            await remaining_room.broadcast_except(uid, {
                "type": "peer_left",
                "from": uid,
            })