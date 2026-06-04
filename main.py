import os
import json
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
# ... 앞부분 생략 ...
from auth import router

import auth
from models import User, Mentor, Booking, MentorAvailability, ChatSession, get_db, create_tables

# 💡 새로 분리한 기능별 라우터들을 가져옵니다.
from routers import users, mentors, bookings, ai, notifications, chat
from routers import chat_router # 👈 💡 우리가 방금 만든 라우터를 불러옵니다!

# 서버 실행 시 시스템의 .env 환경변수를 로드 및 DB 초기화
load_dotenv()
#create_tables()

app = FastAPI()

# ... CORS 설정 부분 생략 ...

app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(users.router)
app.include_router(mentors.router)
app.include_router(bookings.router)
app.include_router(ai.router)
app.include_router(notifications.router)
app.include_router(chat.router)
app.include_router(chat_router.router) # 👈 💡 서버가 우리 라우터를 인식하게끔 이 한 줄을 추가합니다!

@app.get("/")
def root():
    """서버 헬스 체크용 루트 엔드포인트"""
    return {"message": "CoffeeChat Backend Running cleanly!"}

# ... 카카오 인증 콜백 부분 등 나머지 생략 ...


# =====================================================================
# 🔑 카카오 인증 콜백 (auth 모듈과 밀접하게 결합되어 main에 유지)
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