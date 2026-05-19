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
        # 1. 인가 코드로 카카오 액세스 토큰 발급
        kakao_token = auth.get_kakao_token(code)
        
        # 2. 액세스 토큰으로 사용자 정보 가져오기
        kakao_user = auth.get_kakao_user_info(kakao_token)
        provider_id = str(kakao_user.get("id"))
        
        # 카카오 계정의 이메일 추출 (없을 경우 식별자를 활용한 가상 이메일 생성)
        email = kakao_user.get("kakao_account", {}).get("email") or f"{provider_id}@kakao.com"
        
        # 닉네임을 가져오는 경로 보강 (새로운 'name' 필드에 매핑)
        name = (
            kakao_user.get("properties", {}).get("nickname") or 
            kakao_user.get("kakao_account", {}).get("profile", {}).get("nickname") or 
            "이승재"
        )

        # 3. DB에서 기존 유저 확인 및 신규 가입 처리 (PostgreSQL 스키마 매핑)
        user = db.query(User).filter(User.provider_id == provider_id).first()
        
        is_new_user = False
        
        if not user:
            print(f" [DEBUG] DB에 없는 신규 유저 발견! 가입을 시작합니다. ID: {provider_id}")
            user = User(
                email=email,
                name=name, 
                role=UserRole.MENTEE, 
                provider="kakao",
                provider_id=provider_id  # 💡 이 부분이 DB의 provider_id 컬럼에 똑바로 들어가는지 확인
            )
            db.add(user)
            db.commit()          # 💡 PostgreSQL에 실제 INSERT 명령을 날리는 순간
            db.refresh(user)     # 💡 DB가 생성해준 고유 id(pk)값을 파이썬 객체로 받아옴
            is_new_user = True
            print(f" [DEBUG] DB 가입 성공! 생성된 내부 유저 ID(PK): {user.id}")
        else:
            print(f" [DEBUG] 이미 DB에 존재하는 유저입니다. 내부 ID(PK): {user.id} -> 로그인 처리")
            if user.name != name:
                user.name = name
                db.commit()

        # 4. 서비스 전용 JWT 토큰 생성 (sub에 유저의 고유 이메일 주입)
        access_token = auth.create_access_token(data={"sub": user.email, "user_id": user.id})

        safe_name = quote(user.name)
        
        # 💡 [라우팅 분기] 신규 회원이면 /profile-setup 으로 직행하고, 기존 회원이면 메인(/)으로 이동
        if is_new_user:
            frontend_url = f"http://localhost:5173/profile-setup?token={access_token}&name={safe_name}&email={user.email}&id={user.id}"
        else:
            frontend_url = f"http://localhost:5173/?token={access_token}&name={safe_name}"
        
        print(f" [DEBUG] 리다이렉트 대상 주소: {frontend_url}")
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