from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import quote
import auth
from models import User, get_db, create_tables, UserRole
from fastapi.responses import RedirectResponse
# 1. 서버 시작 시 DB 테이블 생성
create_tables()

app = FastAPI()

# 2. CORS 설정: 프론트엔드(localhost)와 백엔드(서버 IP) 간 통신 허용
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
        
        # [수정] 닉네임을 가져오는 경로 보강 (이름이 'User'로 나오는 문제 해결)
        nickname = (
            kakao_user.get("properties", {}).get("nickname") or 
            kakao_user.get("kakao_account", {}).get("profile", {}).get("nickname") or 
            "이승재"  # 기본값 설정
        )

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
        else:
            # 기존 유저의 경우 최신 닉네임으로 업데이트
            if user.nickname != nickname:
                user.nickname = nickname
                db.commit()

        # 4. 서비스 전용 JWT 토큰 생성
        access_token = auth.create_access_token(data={"sub": user.kakao_id})

        # 5. 프론트엔드 리다이렉트 설정
        # [핵심 수정] 프론트엔드가 로컬 PC에서 실행 중이므로 localhost:5173으로 보냅니다.
        safe_nickname = quote(user.nickname)
        frontend_url = f"http://localhost:5173/?token={access_token}&nickname={safe_nickname}"
        
        print(f"🚀 [DEBUG] 리다이렉트 대상 주소: {frontend_url}")
        
        # 안전한 페이지 전환을 위해 302 Found 상태 코드를 사용합니다.
        return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)

    except Exception as e:
        print(f"❌ [ERROR] {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))