from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from typing import Dict, List
import logging

# 배포 환경을 고려한 표준 로깅 설정
logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["Notifications"])

class ConnectionManager:
    """
    실시간 알림을 위한 웹소켓 커넥션 관리 클래스
    배포 환경에서의 다중 세션 관리 및 예외 처리를 포함합니다.
    """
    def __init__(self):
        # Key: user_id (int), Value: WebSocket 객체
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        """클라이언트의 웹소켓 연결 요청을 수락하고 세션을 저장합니다."""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"📡 [WebSocket 연결 성공] User ID: {user_id}")

    def disconnect(self, user_id: int):
        """연결이 끊어진 클라이언트의 세션을 안전하게 제거합니다."""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"🔌 [WebSocket 연결 해제] User ID: {user_id}")

    async def send_personal_message(self, message: dict, user_id: int) -> bool:
        """
        특정 사용자에게 실시간 JSON 알림 데이터를 전송합니다.
        성공 여부를 반환하며, 연결이 끊긴 상태라면 세션을 정리합니다.
        """
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                # 불필요한 반복 로그를 방지하기 위해, 실제 메시지 전송 시점에만 단발성 로깅
                logger.info(f"🔔 [알림 발송 완료] To User {user_id}: {message.get('message')}")
                return True
            except Exception as e:
                logger.error(f"❌ [알림 발송 실패] User {user_id} 연결 유실 추정: {e}")
                self.disconnect(user_id)
        return False

# 싱글톤 인스턴스 생성 (이 객체를 예약 서비스 등에서 임포트하여 알림을 트리거함)
manager = ConnectionManager()

@router.websocket("/ws/notifications/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """프론트엔드와 실시간 양방향 채널을 유지하는 엔드포인트"""
    await manager.connect(user_id, websocket)
    try:
        while True:
            # 클라이언트로부터의 단순 핑(Ping) 혹은 무의미한 메시지 대기 (연결 유지 목적)
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"⚠️ [WebSocket 에러 발생] User {user_id}: {e}")
        manager.disconnect(user_id)

@router.get("/api/notifications")
def get_user_notifications(db: Session = Depends(get_db)):
    """
    [REST API] 최초 페이지 진입 시 과거 알림 이력을 가져오는 엔드포인트
    (웹소켓 연결 전 전체 데이터를 채워주기 위한 용도)
    """
    # 실제 배포 시에는 DB에서 해당 유저의 알림 내역을 조회하는 로직이 들어갑니다.
    # 현재는 빈 배열 구조 유지
    return []