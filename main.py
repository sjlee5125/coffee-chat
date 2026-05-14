from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import quote  # 한글 인코딩을 위해 필수 추가
from models import User, get_db, create_tables, UserRole
import auth

# 서버 시작 시 DB 테이블 생성
create_tables()

app = FastAPI()

# CORS 설정: 프론트엔드와 백엔드 간 통신 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "CoffeeChat Backend Running"}

# --- 카카오 로그인 콜백 엔드포인트 ---
@app.get("/login/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    try:
        # 1. 인가 코드로 카카오 액세스 토큰 발급
        kakao_token = auth.get_kakao_token(code)
        
        # 2. 액세스 토큰으로 사용자 정보 가져오기
        kakao_user = auth.get_kakao_user_info(kakao_token)
        kakao_id = str(kakao_user.get("id"))
        nickname = kakao_user.get("properties", {}).get("nickname")

        # 3. DB에서 기존 유저 확인 및 신규 가입 처리
        user = db.query(User).filter(User.kakao_id == kakao_id).first()
        if not user:
            user = User(
                kakao_id=kakao_id, 
                nickname=nickname, 
                role=UserRole.MENTEE, 
                provider="kakao"
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        # 4. 서비스 전용 JWT 토큰 생성
        access_token = auth.create_access_token(data={"sub": user.kakao_id})

        # 5. 프론트엔드 메인 페이지로 리다이렉트 (토큰 및 닉네임 전달)
        # 한글 이름 인코딩 및 포트 5173 적용
        safe_nickname = quote(user.nickname) if user.nickname else "User"
        frontend_url = f"http://48.211.169.52:5173/?token={access_token}&nickname={safe_nickname}"
        
        print(f"🚀 [DEBUG] 리다이렉트 주소: {frontend_url}")
        return RedirectResponse(url=frontend_url)

    except Exception as e:
        print(f"❌ [ERROR] {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))