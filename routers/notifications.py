import base64
import json
from fastapi import APIRouter, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Dict
import logging
from models import get_db

router = APIRouter()

# =====================================================================
# 🚀 [웹소켓] 0.1초 실시간 알림 파이프라인 관리자
# =====================================================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        """웹소켓 연결을 수락하고 세션을 저장합니다."""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"🟢 [웹소켓 연결] User ID: {user_id} 파이프 개통!")
        print(f"📡 [WebSocket 연결] User ID: {user_id}")

    def disconnect(self, user_id: int):
        """연결이 끊긴 세션을 제거합니다."""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"🔴 [웹소켓 해제] User ID: {user_id}")

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

# 🌟 중요: 다른 파일(예약 API)에서 진동벨을 울릴 수 있도록 manager를 전역으로 빼둡니다.
manager = ConnectionManager()

@router.websocket("/ws/notifications/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """프론트엔드 헤더와 1:1 웹소켓 채널을 유지하는 엔드포인트"""
    await manager.connect(user_id, websocket)
    try:
        while True: 
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception:
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