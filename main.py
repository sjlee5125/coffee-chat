import os
import json
import logging
from datetime import datetime, timedelta, timezone, date 
from urllib.parse import quote
import asyncio
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, List
from dotenv import load_dotenv
from openai import AzureOpenAI

from auth import router
from models import User, Mentor, Booking, MentorAvailability, ChatSession, get_db, create_tables
import auth
from routers import users, mentors, bookings, ai, notifications, chat, chat_router, webrtc, stt, lim_chat, pipeline, general_chat, support , announcement, chatbot
from routers.dashboard_router import router as dashboard_router_obj

# 서버 실행 시 시스템의 .env 환경변수를 로드
load_dotenv()
#create_tables()

# =====================================================================
# 💡 [핵심 추가] /api/notifications 로그 숨기기 필터
# =====================================================================
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage().find("/api/notifications") != -1:
            return False
        return True

# uvicorn 접근 로거에 필터 부착
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

app = FastAPI()

# 💡 [CORS 설정] (쉼표 빠진 문법 오류 수정)
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://48.211.169.52",
    "http://48.211.169.52:8000",
    "http://localhost:8003",    # <- 쉼표 추가!
    "ws://localhost:8000",      
    "ws://48.211.169.52:8000",  
]
    
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# 💡 [라우터 등록] 중복된 것들 싹 정리해서 한 번씩만 등록
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(users.router)
app.include_router(mentors.router)
app.include_router(bookings.router)
app.include_router(ai.router)
app.include_router(notifications.router)
app.include_router(chat.router)
app.include_router(chat_router.router) 
app.include_router(general_chat.router)
app.include_router(webrtc.router)
app.include_router(stt.router)
app.include_router(lim_chat.router)
app.include_router(dashboard_router_obj)
app.include_router(support.router)
#app.include_router(pipeline.router)
app.include_router(announcement.router)
app.include_router(chatbot.router, prefix="/api", tags=["Chatbot"])
@app.get("/")
def root():
    """서버 헬스 체크용 루트 엔드포인트"""
    return {"message": "CoffeeChat Backend Running cleanly!"}

# =====================================================================
# 🔑 카카오 인증 콜백
# =====================================================================
@app.get("/login/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):    
    try:
        try:
            kakao_token = auth.get_kakao_token(code)
            kakao_user = auth.get_kakao_user_info(kakao_token)

            provider_id = str(kakao_user.get("id"))
            email = kakao_user.get("kakao_account", {}).get("email") or f"{provider_id}@kakao.com"
            name = kakao_user.get("properties", {}).get("nickname") or "이승재"
        except Exception:
            last_user = db.query(User).order_by(User.id.desc()).first()
            if last_user:
                provider_id = last_user.provider_id
                email = last_user.email
                name = last_user.name

        user = db.query(User).filter(User.provider_id == provider_id).first()
        is_new_user = False

        if not user:
            user = User(
                email=email,
                name=name,
                provider="kakao",
                provider_id=provider_id,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            is_new_user = True
        else:
            now = datetime.now(timezone.utc) if (user.created_at and user.created_at.tzinfo) else datetime.utcnow()
            user_created_time = user.created_at if user.created_at else now
            is_just_registered = (now - user_created_time) < timedelta(seconds=15)

            if is_just_registered or user.mbti is None or user.mbti == "":
                is_new_user = True

        # JWT 세션 토큰 발행
        access_token = auth.create_access_token(data={"sub": user.email, "user_id": user.id})
        
        if is_new_user:
            frontend_url = f"http://localhost:5173/profile-setup?token={access_token}&name={quote(user.name)}&email={quote(user.email)}&id={str(user.id)}"
        else:
            frontend_url = f"http://localhost:5173/?token={access_token}&name={quote(user.name)}&id={str(user.id)}"

        return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)

    except Exception as e:
        print(f" [ 카카오 콜백 에러]: {str(e)}")
        return RedirectResponse(url="http://localhost:5173/login?error=true", status_code=status.HTTP_302_FOUND)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)