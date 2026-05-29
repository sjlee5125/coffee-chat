import base64
import json
from fastapi import APIRouter, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Dict

# 💡 프로젝트 구조에 맞게 DB와 모델을 import 해주세요! (경로는 상황에 맞게 수정)
from models import Notification, get_db

router = APIRouter()

# =====================================================================
# 🚀 [웹소켓] 0.1초 실시간 알림 파이프라인 관리자
# =====================================================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"🟢 [웹소켓 연결] User ID: {user_id} 파이프 개통!")

    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"🔴 [웹소켓 해제] User ID: {user_id}")

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)

# 🌟 중요: 다른 파일(예약 API)에서 진동벨을 울릴 수 있도록 manager를 전역으로 빼둡니다.
manager = ConnectionManager()

@router.websocket("/ws/notifications/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(user_id, websocket)
    try:
        while True:
            # 브라우저가 꺼지지 않았는지 숨만 쉬면서 확인
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id)

# =====================================================================
# 🔔 [알림 API 1 & 2] 기존 알림 조회 및 읽음 처리 로직
# =====================================================================
@router.get("/api/notifications")
def get_user_notifications(Authorization: str = Header(None), db: Session = Depends(get_db)):
    if not Authorization:
        return []
    try:
        token = Authorization.replace("Bearer ", "")
        payload_b64 = token.split('.')[1]
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.b64decode(payload_b64).decode('utf-8'))
        
        user_id = payload.get("user_id")
        if not user_id:
            return []

        notifications = db.query(Notification).filter(
            Notification.user_id == user_id
        ).order_by(Notification.created_at.desc()).limit(20).all()
        
        return [
            {
                "id": n.id,
                "message": n.message,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None 
            }
            for n in notifications
        ]
    except Exception as e:
        print(f"❌ [알림 조회 에러]: {e}")
        return []

@router.put("/api/notifications/{notification_id}/read")
def mark_notification_as_read(notification_id: int, db: Session = Depends(get_db)):
    try:
        notif = db.query(Notification).filter(Notification.id == notification_id).first()
        if not notif:
            raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다.")
        
        notif.is_read = True
        db.commit()
        return {"message": "성공적으로 읽음 처리되었습니다."}
        
    except Exception as e:
        print(f"❌ [알림 읽음 처리 에러]: {e}")
        raise HTTPException(status_code=500, detail="알림 처리 중 오류가 발생했습니다.")