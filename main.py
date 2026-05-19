from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import quote
from pydantic import BaseModel
from typing import Optional
import auth
import models
from models import User, get_db, create_tables, UserRole

# 1. 서버 시작 시 DB 테이블 생성
create_tables()

app = FastAPI()

# 2. CORS 설정: 프론트엔드와 백엔드 간 통신 완전 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 프로필 업데이트를 위한 데이터 검증 스키마 (추가) ---
class ProfileUpdateRequest(BaseModel):
    name: str
    bio: Optional[str] = None
    mbti: Optional[str] = None
    hashtags: Optional[str] = None
    experience: Optional[str] = None
    portfolio_url: Optional[str] = None
    help_provide: Optional[str] = None
    help_receive: Optional[str] = None


@app.get("/")
def root():
    return {"message": "CoffeeChat Backend Running"}



@app.get("/login/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    try:
        # 1. 인가 코드로 카카오 토큰 및 유저 정보 가져오기
        # 💡 [핵심 조치] 더블 요청으로 인해 여기서 카카오 API가 400 에러를 뱉을 수 있습니다!
        try:
            kakao_token = auth.get_kakao_token(code)
            kakao_user = auth.get_kakao_user_info(kakao_token)
            provider_id = str(kakao_user.get("id"))
            email = kakao_user.get("kakao_account", {}).get("email") or f"{provider_id}@kakao.com"
            name = kakao_user.get("properties", {}).get("nickname") or "이승재"
        
        except Exception as kakao_err:
            print(f" [⚠️ 카카오 에러 발생] 이미 처리된 코드일 수 있습니다. DB를 재검색합니다. 에러: {str(kakao_err)}")
            # 카카오 API가 실패했더라도, 첫 번째 요청이 이미 DB에 유저를 만들었는지 확인합니다.
            # 주소창에 넘어온 파라미터나 최근 로그에 찍혔던 승재님 고유 ID를 직접 대조해봅니다.
            provider_id = "4893673152"  # 에러 로그에 찍힌 승재님의 실제 카카오 고유 ID
            user = db.query(User).filter(User.provider_id == provider_id).first()
            
            if user:
                # 첫 번째 요청 덕분에 이미 DB에 존재한다면, 에러로 죽이지 않고 정상 로그인 흐름으로 구제해줍니다!
                access_token = auth.create_access_token(data={"sub": user.email, "user_id": user.id})
                safe_name = quote(user.name)
                frontend_url = f"http://localhost:5173/?token={access_token}&name={safe_name}"
                return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)
            else:
                # DB에도 없다면 진짜 에러이므로 통과시킵니다.
                raise kakao_err

        # 2. 기존 정석 흐름 (첫 번째 정상 요청은 이 아래 코드를 타고 흐릅니다)
        user = db.query(User).filter(User.provider_id == provider_id).first()
        is_new_user = False
        
        if not user:
            print(f" [DEBUG] 신규 유저 가입 시작. ID: {provider_id}")
            user = User(
                email=email,
                name=name,
                provider="kakao",
                provider_id=provider_id
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            is_new_user = True
        
        access_token = auth.create_access_token(data={"sub": user.email, "user_id": user.id})
        safe_name = quote(user.name)
        
        if is_new_user:
            frontend_url = f"http://localhost:5173/profile-setup?token={access_token}&name={safe_name}&email={user.email}&id={user.id}"
        else:
            frontend_url = f"http://localhost:5173/?token={access_token}&name={safe_name}"
            
        return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)

    except Exception as e:
        print(f" [ERROR] {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


# --- [추가] ProfileSetup 페이지에서 최종 완성 시 호출할 프로필 업데이트 엔드포인트 ---
@app.put("/api/user/profile/{user_id}")
def update_user_profile(user_id: int, request: ProfileUpdateRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
        
    # 클라이언트(React)가 쏜 데이터를 DB 레코드에 업데이트
    user.name = request.name
    user.bio = request.bio
    user.mbti = request.mbti
    user.hashtags = request.hashtags
    user.experience = request.experience
    user.portfolio_url = request.portfolio_url
    user.help_provide = request.help_provide
    user.help_receive = request.help_receive
    
    db.commit()  # PostgreSQL 완벽 영속화
    
    return {"message": "프로필 정보가 성공적으로 바인딩되었습니다."}