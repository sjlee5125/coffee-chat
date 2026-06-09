import json
import logging
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# 터미널에 로그가 예쁘게 출력되도록 기본 설정 (이미 main 등에서 설정되어 있다면 생략 가능)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

router = APIRouter(tags=["General Chat"])

class ChatRoomManager:
    def __init__(self):
        # 구조: { "room_id": { "user_id": WebSocket } }
        self.rooms: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, room_id: str, user_id: str, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
        self.rooms[room_id][user_id] = websocket
        
        # 🔍 디버깅 로그: 현재 방에 누가 머물고 있는지 리스트를 출력합니다.
        current_users = list(self.rooms[room_id].keys())
        logger.info(f"🔑 [소켓 연결] 방={room_id}에 유저={user_id} 입장 | 현재 방 인원: {current_users}")

    def disconnect(self, room_id: str, user_id: str):
        if room_id in self.rooms and user_id in self.rooms[room_id]:
            del self.rooms[room_id][user_id]
            logger.info(f"❌ [소켓 해제] 방={room_id}에서 유저={user_id} 퇴장")
            
            if not self.rooms[room_id]:
                del self.rooms[room_id]
                logger.info(f"🧹 [방 삭제] 방={room_id}에 남은 인원이 없어 방을 완전히 비웁니다.")

    async def broadcast(self, room_id: str, exclude_user_id: str, message: dict):
        if room_id not in self.rooms:
            logger.warning(f"⚠️ [브로드캐스트 실패] 방={room_id}이 존재하지 않습니다.")
            return

        active_users = list(self.rooms[room_id].keys())
        logger.info(f"📢 [브로드캐스트 시작] 방={room_id} | 참여자들={active_users} | 보낸 사람={exclude_user_id}")

        for u_id, ws in self.rooms[room_id].items():
            # 메시지를 보낸 본인을 제외하고 나머지 사람들에게만 송신
            if u_id != exclude_user_id:
                try:
                    await ws.send_json(message)
                    logger.info(f"   └✅ 유저={u_id} 에게 메시지 전달 성공!")
                except Exception as e:
                    # 🚨 숨겨져 있던 에러를 터미널에 강제로 드러냅니다.
                    logger.error(f"   └❌ 유저={u_id} 에게 전송 중 에러 발생: {e}")

chat_manager = ChatRoomManager()


@router.websocket("/ws/chat/{booking_id}/{user_id}")
async def general_chat_endpoint(
    websocket: WebSocket,
    booking_id: int,
    user_id: int,
):
    # 데이터 타입을 확실하게 문자열로 통일하여 매칭 오류 방지
    room_id = str(booking_id)
    uid = str(user_id)
    
    await chat_manager.connect(room_id, uid, websocket)

    try:
        while True:
            # 프론트엔드로부터 텍스트 데이터 수신
            raw = await websocket.receive_text()
            logger.info(f"📩 [백엔드 수신] 방={room_id} | 유저={uid} -> 데이터: {raw}")
            
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as je:
                logger.error(f"⚠️ [JSON 파싱 에러] 유저={uid}가 보낸 데이터가 올바른 JSON 형식이 아닙니다: {je}")
                continue

            # 방 안의 다른 사람들에게 뿌리기
            await chat_manager.broadcast(room_id, exclude_user_id=uid, message=data)

    except WebSocketDisconnect:
        logger.info(f"🔌 [웹소켓 끊김] 유저={uid}가 정상적으로 연결을 종료했습니다.")
    except Exception as e:
        logger.error(f"💥 [웹소켓 예외] 방={room_id} 유저={uid} 통신 중 에러: {e}")
    finally:
        chat_manager.disconnect(room_id, uid)