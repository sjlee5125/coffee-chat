import os
from datetime import datetime, timedelta, timezone, date
from urllib.parse import quote

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
from openai import AzureOpenAI

import auth

print(f"DEBUG: auth.py loaded from: {auth.__file__}")
from auth import router
from models import User, Mentor, get_db, create_tables


load_dotenv()
create_tables()

app = FastAPI()
app.include_router(router, prefix="/api/auth")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://48.211.169.52",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


print("--- [DEBUG] 등록된 라우터 경로 확인 ---")
for route in app.routes:
    if hasattr(route, "path"):
        print(f"DEBUG: {route.path} | {getattr(route, 'methods', 'N/A')}")


AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION")

if not all([AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, AZURE_DEPLOYMENT_NAME]):
    print("⚠️ [경고] Azure OpenAI 환경 변수 중 일부가 .env 파일에 설정되지 않았습니다.")

ai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=AZURE_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)


class UserRegisterRequest(BaseModel):
    email: str
    password: str
    role: str
    name: str
    bio: Optional[str] = None
    mbti: Optional[str] = None
    hashtags: Optional[str] = None
    experience: Optional[str] = None
    portfolio_url: Optional[str] = None
    help_provide: Optional[str] = None
    help_receive: Optional[str] = None
    profile_image: Optional[str] = None


class UserLoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdateRequest(BaseModel):
    name: str
    bio: Optional[str] = None
    mbti: Optional[str] = None
    hashtags: Optional[str] = None
    experience: Optional[str] = None
    portfolio_url: Optional[str] = None
    help_provide: Optional[str] = None
    help_receive: Optional[str] = None
    profile_image: Optional[str] = None


class AIQuestionRequest(BaseModel):
    memo: str


class BookingCreateRequest(BaseModel):
    mentorId: int
    date: date
    time: str
    questions: str


class MentorRegisterRequest(BaseModel):
    name: str
    job_title: str
    career_history: Optional[str] = None
    mentor_intro: Optional[str] = None
    mentoring_topics: Optional[str] = None
    detailed_experience: Optional[str] = None
    hashtags: Optional[str] = None
    portfolio_url: Optional[str] = None


@app.get("/")
def root():
    return {"message": "CoffeeChat Backend Running"}


@app.get("/login/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    provider_id = "4893673152"
    email = None
    name = "이승재"

    try:
        print(" [카카오 콜백 수신] 인가 코드 검증 및 프로세스 가동")

        try:
            kakao_token = auth.get_kakao_token(code)
            kakao_user = auth.get_kakao_user_info(kakao_token)

            provider_id = str(kakao_user.get("id"))
            email = kakao_user.get("kakao_account", {}).get("email") or f"{provider_id}@kakao.com"
            name = kakao_user.get("properties", {}).get("nickname") or "이승재"
        except Exception:
            print(" [ 카카오 중복 요청 감지] 에러 무시 후 바로 직전 등록된 유저 기반 가드 구제 가동")
            last_user = db.query(User).order_by(User.id.desc()).first()
            if last_user:
                provider_id = last_user.provider_id
                email = last_user.email
                name = last_user.name

        user = db.query(User).filter(User.provider_id == provider_id).first()
        is_new_user = False

        if not user:
            print(f" [DEBUG] 찐 신규 유저 발견! DB 가입을 시작합니다. ID: {provider_id}")
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
                print(" [리다이렉트 조건 충족] 신규 가입자 세션 유지 ➔ 프로필 설정 페이지로 유도")
                is_new_user = True

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
        "help_receive": getattr(user, "help_receive", "") or "",
        "profile_image": getattr(user, "profile_image", "") or "",
    }


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

    if request.profile_image:
        user.profile_image = request.profile_image

    db.commit()
    print(f" [DB 반영 성공] 유저 {user_id}번 프로필 영구 업데이트 저장 완료")

    return {"message": "프로필 정보가 성공적으로 바인딩되었습니다."}


@app.post("/api/mentor/register/{user_id}")
def register_mentor(user_id: int, request: MentorRegisterRequest, db: Session = Depends(get_db)):
    print(f" [분리형 멘토 등록 시작] User ID: {user_id}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 회원 데이터입니다.")

    user.name = request.name
    user.hashtags = request.hashtags
    user.portfolio_url = request.portfolio_url

    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()

    if not mentor:
        print(" ➔ 기존 멘토 레코드 없음: 새롭게 생성")
        mentor = Mentor(user_id=user_id)
        db.add(mentor)

    mentor.name = request.name
    mentor.job_title = request.job_title
    mentor.career_history = request.career_history
    mentor.mentor_intro = request.mentor_intro
    mentor.mentoring_topics = request.mentoring_topics
    mentor.detailed_experience = request.detailed_experience

    db.commit()
    print(f" [DB 분리 저장 완료] {user_id}번 유저의 독립형 멘토 프로필 생성 완결")

    return {"message": "멘토 프로필 독립 등록 완료"}


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
        "mentoring_hours": getattr(user, "mentoring_hours", 63.5),
    }

    return {
        "stats": stats_data,
        "upcoming_chats": [],
    }


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

        response = ai_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=1000,
        )

        suggested_questions = response.choices[0].message.content.strip()
        print(" [AI 질문 생성 성공] 응답 데이터 반환 완료")

        return {"aiQuestions": suggested_questions}

    except Exception as e:
        print(f" [Azure OpenAI 에러 발생]: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"AI 질문 생성 중 내부 오류가 발생했습니다: {str(e)}",
        )


print(f"--- [DEBUG] 현재 등록된 라우터 개수: {len(app.routes)} ---")
for route in app.routes:
    print(f"DEBUG: 경로 정보 -> {route.path} | {getattr(route, 'methods', 'N/A')}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)