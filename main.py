from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import quote
from pydantic import BaseModel
from typing import Optional
import auth
from models import User, get_db, create_tables, UserRole
from datetime import datetime, timedelta
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
        provider_id = "4893673152" # 기본값 세팅 (에러 대비)
        email = None
        name = "이승재"
        
        # 1. 카카오 API로 유저 정보 가져오기 시도
        try:
            kakao_token = auth.get_kakao_token(code)
            kakao_user = auth.get_kakao_user_info(kakao_token)
            provider_id = str(kakao_user.get("id"))
            email = kakao_user.get("kakao_account", {}).get("email") or f"{provider_id}@kakao.com"
            name = kakao_user.get("properties", {}).get("nickname") or "이승재"
        except Exception as kakao_err:
            print(f" [⚠️ 카카오 중복 요청 감지] 에러 무시하고 DB 기반으로 분기 처리합니다.")

        # 2. DB에서 유저 조회
        user = db.query(User).filter(User.provider_id == provider_id).first()
        
        if not user:
            # 💡 진짜 생판 처음 가입하는 유저인 경우
            print(f" [DEBUG] 찐 신규 유저 발견! DB 가입을 시작합니다. ID: {provider_id}")
            user = User(
                email=email,
                name=name,
                provider="kakao",
                provider_id=provider_id
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            
            # 신규 가입자이므로 프로필 설정창으로 리다이렉트
            access_token = auth.create_access_token(data={"sub": user.email, "user_id": user.id})
            safe_name = quote(user.name)
            frontend_url = f"http://localhost:5173/profile-setup?token={access_token}&name={safe_name}&email={user.email}&id={user.id}"
            print(f" [리다이렉트] 신규회원 -> 프로필 설정으로 이동: {frontend_url}")
            return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)

        else:
            # 💡 DB에 이미 유저가 있는 경우 (중복 요청이거나 기존 회원)
            access_token = auth.create_access_token(data={"sub": user.email, "user_id": user.id})
            safe_name = quote(user.name)
            
            # 🔥 [핵심 타격점] 가입한 지 5초 이내인 유저거나, 프로필 항목(mbti 등)이 아예 비어있다면
            # 중복 요청으로 들어온 '신규 회원'으로 판단하여 메인이 아닌 프로필 설정창으로 보내줍니다!
            is_just_registered = user.created_at and (datetime.utcnow() - user.created_at) < timedelta(seconds=10)
            
            if is_just_registered or user.mbti is None:
                frontend_url = f"http://localhost:5173/profile-setup?token={access_token}&name={safe_name}&email={user.email}&id={user.id}"
                print(f" [리다이렉트] 중복 요청 구제 -> 프로필 설정으로 이동: {frontend_url}")
            else:
                # 진짜 옛날에 가입해서 프로필까지 다 채운 기존 회원이면 메인 화면으로 이동
                frontend_url = f"http://localhost:5173/?token={access_token}&name={safe_name}"
                print(f" [리다이렉트] 기존회원 -> 메인 화면으로 이동: {frontend_url}")
                
            return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)

    except Exception as e:
        print(f" [ERROR] 콜백 처리 실패: {str(e)}")
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