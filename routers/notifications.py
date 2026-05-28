from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from typing import Dict
from models import get_db

# 라우터 생성
router = APIRouter(tags=["Notifications"])

# ─── 실시간 알림 웹소켓 매니저 ───
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"📡 [WebSocket 연결] User ID: {user_id}")

    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"🔌 [WebSocket 연결 해제] User ID: {user_id}")

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)

manager = ConnectionManager()

# ─── API 라우터 구역 ───

@router.websocket("/ws/notifications/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(user_id, websocket)
    try:
        while True: 
            await websocket.receive_text()
    except WebSocketDisconnect: 
        manager.disconnect(user_id)


@router.get("/api/notifications")
def get_user_notifications(db: Session = Depends(get_db)):
    """프론트엔드 헤더 알림 요청용 (현재는 빈 배열 반환)"""
    return []