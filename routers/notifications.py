from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from typing import Dict
import logging
from models import get_db
# 배포 환경을 고려한 uvicorn 표준 로거 설정
logger = logging.getLogger("uvicorn.error")

# 라우터 생성
router = APIRouter(tags=["Notifications"])

# ─── 실시간 알림 웹소켓 매니저 ───
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        """웹소켓 연결을 수락하고 세션을 저장합니다."""
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        """연결이 끊긴 세션을 제거합니다."""
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send_personal_message(self, message: dict, user_id: int):
        """
        [개선] 특정 사용자에게 알림을 보냅니다.
        사용자 요청에 따라 실제 알림이 발송되는 '그 당시'에만 로그가 기록됩니다.
        """
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                # 💡 실제 알림 메시지가 전송되는 시점에만 단발성으로 로그 출력
                logger.info(f"🔔 [실시간 알림 발송] User ID {user_id} -> {message.get('message')}")
            except Exception:
                # 전송 실패 시 안전하게 커넥션 정리
                self.disconnect(user_id)

manager = ConnectionManager()

@router.websocket("/ws/notifications/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """프론트엔드 헤더와 1:1 웹소켓 채널을 유지하는 엔드포인트"""
    await manager.connect(user_id, websocket)
    try:
        while True: 
            # 연결 유지를 위해 대기 (프론트엔드가 보낸 텍스트가 와도 로그를 남기지 않고 조용히 넘김)
            await websocket.receive_text()
    except WebSocketDisconnect: 
        manager.disconnect(user_id)
    except Exception:
        manager.disconnect(user_id)


@router.get("/api/notifications")
def get_user_notifications(db: Session = Depends(get_db)):
    """
    프론트엔드 초기 진입용 엔드포인트
    (프론트엔드에서 10초마다 때리던 Polling을 제거했으므로 더 이상 무한 로그가 쌓이지 않습니다)
    """
    # 내부 임포트는 지워줍니다.
    return []