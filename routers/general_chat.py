import json
import logging
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# 일반 채팅 전용 라우터 (태그명도 변경)
router = APIRouter(tags=["General Chat"])

class ChatRoomManager:
    def __init__(self):
        self.rooms: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, room_id: str, user_id: str, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
        self.rooms[room_id][user_id] = websocket

    def disconnect(self, room_id: str, user_id: str):
        if room_id in self.rooms and user_id in self.rooms[room_id]:
            del self.rooms[room_id][user_id]
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    async def broadcast(self, room_id: str, exclude_user_id: str, message: dict):
        if room_id in self.rooms:
            for u_id, ws in self.rooms[room_id].items():
                if u_id != exclude_user_id:
                    try:
                        await ws.send_json(message)
                    except Exception:
                        pass

chat_manager = ChatRoomManager()


@router.websocket("/ws/chat/{booking_id}/{user_id}")
async def general_chat_endpoint(
    websocket: WebSocket,
    booking_id: int,
    user_id: int,
):
    room_id = str(booking_id)
    uid = str(user_id)
    
    await chat_manager.connect(room_id, uid, websocket)
    logger.info(f"[일반채팅] 입장 room={room_id} uid={uid}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            await chat_manager.broadcast(room_id, exclude_user_id=uid, message=data)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[일반채팅] 예외 room={room_id} uid={uid}: {e}")
    finally:
        chat_manager.disconnect(room_id, uid)
        logger.info(f"[일반채팅] 퇴장 room={room_id} uid={uid}")