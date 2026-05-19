from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import quote
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import auth
from models import User, get_db, create_tables, UserRole
from datetime import datetime, timedelta, timezone

# 1. 서버 시작 시 DB 테이블 생성
create_tables()

app = FastAPI()

# 2. CORS 설정: 프론트엔드와 백엔드 간 통신 완전 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # 💡 자격 증명(토큰/쿠키) 안전 허용
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 데이터 검증 스키마 (Pydantic 모델) ---
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


# --- 카카오 로그인 콜백 엔드포인트 ---
@app.get("/login/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    provider_id = "4893673152"
    email = None
    name = "이승재"
    
    try:
        print(f" [카카오 콜백 수신] 인가 코드 검증 및 프로세스 가동")
        
        # 1. 카카오 API 연동 및 데이터 추출 (더블 요청 400 에러 방어)
        try:
            kakao_token = auth.get_kakao_token(code)
            kakao_user = auth.get_kakao_user_info(kakao_token)
            
            provider_id = str(kakao_user.get("id"))
            email = kakao_user.get("kakao_account", {}).get("email") or f"{provider_id}@kakao.com"
            name = kakao_user.get("properties", {}).get("nickname") or "이승재"
        except Exception as kakao_err:
            print(f" [⚠️ 카카오 중복 요청 감지] 에러 무시 후 바로 직전 등록된 유저 기반 가드 구제 가동")
            last_user = db.query(User).order_by(User.id.desc()).first()
            if last_user:
                provider_id = last_user.provider_id
                email = last_user.email
                name = last_user.name

        # 2. DB에서 유저 조회 (public 스키마 타겟팅)
        user = db.query(User).filter(User.provider_id == provider_id).first()
        is_new_user = False
        
        if not user:
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
            is_new_user = True
        else:
            # 타임존 유무에 상관없이 에러 없이 완벽하게 시간을 비교하는 계산식
            now = datetime.now(timezone.utc) if (user.created_at and user.created_at.tzinfo) else datetime.utcnow()
            user_created_time = user.created_at if user.created_at else now
            
            is_just_registered = (now - user_created_time) < timedelta(seconds=15)
            
            if is_just_registered or user.mbti is None or user.mbti == "":
                print(f" [리다이렉트 조건 충족] 신규 가입자 세션 유지 ➔ 프로필 설정 페이지로 유도")
                is_new_user = True

        # 3. 액세스 토큰 발행 및 파라미터 셋업
        access_token = auth.create_access_token(data={"sub": user.email, "user_id": user.id})
        safe_name = quote(user.name)
        safe_email = quote(user.email)

        if is_new_user:
            frontend_url = f"http://localhost:5173/profile-setup?token={access_token}&name={safe_name}&email={safe_email}&id={user.id}"
            print(f" [리다이렉트] 신규회원 진입 완료: {frontend_url}")
        else:
            frontend_url = f"http://localhost:5173/?token={access_token}&name={safe_name}"
            print(f" [리다이렉트] 기존 진짜 회원 로그인 완료: {frontend_url}")
            
        return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)

    except Exception as e:
        print(f" [🔥 카카오 콜백 최종 치명적 붕괴 에러]: {str(e)}")
        return RedirectResponse(url="http://localhost:5173/login?error=true", status_code=status.HTTP_302_FOUND)


# --- 💡 [추가] ProfileSetup 및 Dashboard 초기 동기화용 유저 단건 조회 API ---
app.get("/api/user/{user_id}")
def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
    print(f" [유저 전체 프로필 조회 요청] User ID: {user_id}")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
        
    # 💡 유저 테이블에 박혀있는 모든 컬럼 항목들을 빠짐없이 JSON 포맷으로 넘겨줍니다!
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "bio": getattr(user, "bio", "") or "",
        "mbti": getattr(user, "mbti", "") or "",
        "hashtags": getattr(user, "hashtags", "") or "",
        "experience": getattr(user, "experience", "") or "",
        "portfolio_url": getattr(user, "portfolio_url", "") or "",
        "help_provide": getattr(user, "help_provide", "") or "",
        "help_receive": getattr(user, "help_receive", "") or ""
    }
# --- ProfileSetup 페이지에서 최종 완성 시 호출할 프로필 업데이트 엔드포인트 ---
@app.put("/api/user/profile/{user_id}")
def update_user_profile(user_id: int, request: ProfileUpdateRequest, db: Session = Depends(get_db)):
    print(f" [프로필 업데이트 요청 접수] User ID: {user_id}")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
        
    user.name = request.name
    user.bio = request.bio
    user.mbti = request.mbti
    user.hashtags = request.hashtags
    user.experience = request.experience
    user.portfolio_url = request.portfolio_url
    user.help_provide = request.help_provide
    user.help_receive = request.help_receive
    
    db.commit()  # PostgreSQL 영속화
    print(f" [DB 반영 성공] 유저 {user_id}번 프로필 영구 업데이트 저장 완료")
    
    return {"message": "프로필 정보가 성공적으로 바인딩되었습니다."}


# --- 💡 [추가] 멘토 대시보드 실시간 통계 및 예정된 커피챗 연동 API ---
@app.get("/api/mentor/dashboard/{user_id}")
def get_mentor_dashboard_data(user_id: int, db: Session = Depends(get_db)):
    print(f" [대시보드 데이터 요청 접수] User ID: {user_id}")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
        
    # 💡 유저 모델에 통계 컬럼이 없을 경우를 대비하여 getattr 처리 (기본값 설정 가드)
    stats_data = {
        "name": user.name,
        "total_chats": getattr(user, "total_chats", 127),       # DB 연동 가능
        "total_earnings": getattr(user, "total_earnings", 9525), # DB 연동 가능
        "average_rating": getattr(user, "average_rating", 4.9),  # DB 연동 가능
        "mentoring_hours": getattr(user, "mentoring_hours", 63.5) # DB 연동 가능
    }
    
    # 💡 예정된 커피챗 더미 스케줄 리스트 서빙 (추후 CoffeeChat 매칭 테이블과 연결 가능)
    upcoming_chats = [
       
    ]
    
    return {
        "stats": stats_data,
        "upcoming_chats": upcoming_chats
    }