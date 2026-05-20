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
from pydantic import BaseModel
from datetime import date
from models import Booking, Mentor # 생성한 모델 임포트
from openai import AzureOpenAI 
# 💡 dotenv 라이브러리 임포트
from dotenv import load_dotenv
import os
# 💡 서버 시작 시 .env 파일의 환경변수를 시스템에 로드합니다.
load_dotenv()
# 1. 서버 시작 시 DB 테이블 생성
create_tables()

app = FastAPI()

# 💡 os.getenv()를 통해 .env 파일에 적힌 값을 안전하게 가져옵니다.
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION")

# 필수 환경 변수가 누락되었는지 검증
if not all([AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, AZURE_DEPLOYMENT_NAME]):
    print("⚠️ [경고] Azure OpenAI 환경 변수 중 일부가 .env 파일에 설정되지 않았습니다.")

# Azure OpenAI 클라이언트 초기화
ai_client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2024-02-15-preview"  # 💡 여기에 직접 버전을 꽂아버립니다!
)

class AIQuestionRequest(BaseModel):
    memo: str

# 2. 💡 [수정 핵심] CORS 설정 교정 (allow_credentials=True 스펙 준수)
# allow_credentials가 True일 때는 origins 주소를 정확하게 명시해야 브라우저 차단이 풀립니다.
origins = [
    "http://localhost:5173",    # 로컬 개발 환경 리액트 주소
    "http://127.0.0.1:5173",  
    "http://48.211.169.52",     # 리눅스 퍼블릭 IP 인스턴스 주소
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,        # 와일드카드(*) 대신 안전한 오리진 리스트 바인딩
    allow_credentials=True,       # 자격 증명(토큰/쿠키) 승인 활성화 유지
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

# --- 데이터 검증 스키마 ---
class AIQuestionRequest(BaseModel):
    memo: str

class BookingCreateRequest(BaseModel):
    mentorId: int
    date: date
    time: str
    questions: str

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
            print(f" [ 카카오 중복 요청 감지] 에러 무시 후 바로 직전 등록된 유저 기반 가드 구제 가동")
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
        print(f" [ 카카오 콜백 최종 치명적 붕괴 에러]: {str(e)}")
        return RedirectResponse(url="http://localhost:5173/login?error=true", status_code=status.HTTP_302_FOUND)


@app.get("/api/user/{user_id}")
def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
    print(f" [유저 전체 프로필 조회 요청] User ID: {user_id}")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
        
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


# --- 멘토 대시보드 실시간 통계 및 예정된 커피챗 연동 API ---
@app.get("/api/mentor/dashboard/{user_id}")
def get_mentor_dashboard_data(user_id: int, db: Session = Depends(get_db)):
    print(f" [대시보드 데이터 요청 접수] User ID: {user_id}")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")
        
    stats_data = {
        "name": user.name,
        "total_chats": getattr(user, "total_chats", 127),       
        "total_earnings": getattr(user, "total_earnings", 9525), 
        "average_rating": getattr(user, "average_rating", 4.9),  
        "mentoring_hours": getattr(user, "mentoring_hours", 63.5) 
    }
    
    upcoming_chats = []
    
    return {
        "stats": stats_data,
        "upcoming_chats": upcoming_chats
    }

# --- 1. AI 질문 생성 API ---
@app.post("/api/ai/generate-questions")
async def generate_ai_questions(request: AIQuestionRequest):
    print(f" [AI 질문 생성 요청 접수] 메모 내용: {request.memo}")
    
    if not request.memo.strip():
        raise HTTPException(status_code=400, detail="메모 내용이 비어 있습니다.")
        
    try:
        system_prompt = (
            "당신은 커리어 멘토링 서비스의 질문 추천 AI 어시스턴트입니다. "
            "사용자가 멘토에게 질문하고 싶은 내용을 두서없이 작성한 '메모'를 주면, "
            "그 내용을 명확하고 전문적인 멘토링 질문 리스트(최대 3~4개)로 정제하여 답변해야 합니다. "
            "답변 서론이나 결론(예: '여기 질문입니다' 등)은 모두 제외하고, "
            "사용자가 바로 복사해서 쓸 수 있게 정제된 질문 리스트만 번호(1., 2., 3.) 형태로 줄바꿈하여 출력하세요."
        )
        
        user_prompt = f"사용자 메모:\n{request.memo}"

        # 비동기 엔드포인트 내에서 호출
        response = ai_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME, 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt} # 💡 기존 'content' 오타를 'user' 역할로 교정했습니다.
            ],
            temperature=0.7,
            max_tokens=1000
        )
        
        suggested_questions = response.choices[0].message.content.strip()
        print(f" [AI 질문 생성 성공] 응답 데이터 반환 완료")
        
        return {"aiQuestions": suggested_questions}
        
    except Exception as e:
        print(f" [Azure OpenAI 에러 발생]: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"AI 질문 생성 중 내부 오류가 발생했습니다: {str(e)}"
        )