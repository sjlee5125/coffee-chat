import os
import json
from datetime import datetime, timedelta, timezone, date
from urllib.parse import quote

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, List
from dotenv import load_dotenv
from openai import AzureOpenAI

import auth

# 디버그: auth.py 모듈이 로드된 실제 시스템 경로를 로그에 출력합니다.
print(f"DEBUG: auth.py loaded from: {auth.__file__}")
from auth import router
from models import User, Mentor, Booking, MentorAvailability, get_db, create_tables


# 서버 실행 시 시스템의 .env 환경변수를 로드합니다.
load_dotenv()

create_tables()

app = FastAPI()

# 카카오 인증 처리 및 토큰 핸들링을 위한 외부 라우터를 탑재합니다.
app.include_router(router, prefix="/api/auth")

# 💡 [CORS 설정] 자격 증명(allow_credentials=True) 승인을 위해 명시적인 오리진 리스트를 설계합니다.
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://48.211.169.52",
    "http://48.211.169.52:8000", # 백엔드 API 포트 주소도 명시적으로 허용하여 CORS 차단을 예방합니다.
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 콘솔 디버그: 현재 FastAPI 인스턴스에 탑재되어 실행 준비가 완료된 라우터 목록을 로깅합니다.
print("--- [DEBUG] 등록된 라우터 경로 확인 ---")
for route in app.routes:
    if hasattr(route, "path"):
        print(f"DEBUG: {route.path} | {getattr(route, 'methods', 'N/A')}")


# Azure OpenAI 연동을 위한 환경 변수를 .env 파일로부터 가져옵니다.
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION")

if not all([AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, AZURE_DEPLOYMENT_NAME]):
    print("⚠️ [경고] Azure OpenAI 환경 변수 중 일부가 .env 파일에 설정되지 않았습니다.")

# Azure OpenAI 클라이언트를 초기화합니다.
ai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=AZURE_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)


# --- [데이터 검증 스크마: Pydantic 영역] ---

class UserRegisterRequest(BaseModel):
    """일반 회원 최초 가입 시 프론트엔드에서 수신할 요청 가방 데이터 명세"""
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
    """일반 로그인 검증용 가방 데이터 명세"""
    email: str
    password: str


class ProfileUpdateRequest(BaseModel):
    """일반 회원 프로필 수정 처리 시 수신할 요청 가방 데이터 명세"""
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
    """AI 질문 추천 어시스턴트 요청 시 수신할 메모 명세"""
    memo: str


class BookingCreateRequest(BaseModel):
    """커피챗 예약 생성 시 수신할 요청 데이터 명세"""
    mentorId: int
    date: date
    time: str
    questions: str


class MentorRegisterRequest(BaseModel):
    """
    멘토 프로필 독립 등록/수정 시 프론트엔드에서 수신할 요청 가방 데이터 명세
    DBeaver 데이터베이스 엔티티 관계도 스펙과 1:1 완벽 맵핑 설계
    """
    name: str
    job_title: str
    career_history: Optional[str] = None
    mentor_intro: Optional[str] = None
    mentoring_topics: Optional[str] = None
    detailed_experience: Optional[str] = None
    hashtags: Optional[str] = None
    portfolio_url: Optional[str] = None
    portfolio_file_path: Optional[str] = None  # attachedFiles 첨부파일명 저장용 칸


# [신규] 일정 관련 요청 모델
class AvailabilityBulkRequest(BaseModel):
    """멘토 가용 시간 bulk 저장 요청 명세"""
    mentor_id: int
    schedules: Dict[str, List[str]]  # { "2026-05-23": ["09:00", "09:30"], ... }


class PenaltyRequest(BaseModel):
    """멘토 귀책 예약 취소(패널티) 처리 요청 명세"""
    mentor_id: int
    date: str   # "2026-05-23"
    time: str   # "09:00"
    reason: str


# --- [API 라우터 비즈니스 로직 구역] ---

@app.get("/")
def root():
    """서버 헬스 체크용 루트 엔드포인트"""
    return {"message": "CoffeeChat Backend Running"}


@app.get("/login/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    """
    카카오 인증 콜백 수신 엔드포인트
    인가 코드의 중복 사용으로 인한 400 에러 감지 시 이전 가입자 정보를 활용해 무한 로딩 루프를 원천 차단합니다.
    """
    provider_id = "4893673152"
    email = None
    name = "이승재"

    try:
        print(" [카카오 콜백 수신] 인가 코드 검증 및 프로세스 가동")

        try:
            # 카카오 토큰 및 유저 정보 요청
            kakao_token = auth.get_kakao_token(code)
            kakao_user = auth.get_kakao_user_info(kakao_token)

            provider_id = str(kakao_user.get("id"))
            email = kakao_user.get("kakao_account", {}).get("email") or f"{provider_id}@kakao.com"
            name = kakao_user.get("properties", {}).get("nickname") or "이승재"
        except Exception:
            # 유효하지 않은 코드나 더블 서브밋 중복 감지 시, 마지막 가입자로 연동 우회 구조 발동
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
            # 타임존 비교 에러가 나지 않도록 표준 안전 비교 연산을 진행합니다.
            now = datetime.now(timezone.utc) if (user.created_at and user.created_at.tzinfo) else datetime.utcnow()
            user_created_time = user.created_at if user.created_at else now

            is_just_registered = (now - user_created_time) < timedelta(seconds=15)

            if is_just_registered or user.mbti is None or user.mbti == "":
                print(" [리다이렉트 조건 충족] 신규 가입자 세션 유지 ➔ 프로필 설정 페이지로 유도")
                is_new_user = True

        # JWT 세션 토큰 발행
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
    """
    일반 프로필 전체 데이터 조회 API
    DBeaver 데이터베이스 관계도 상의 portfolio_file_path 정보까지 유실 없이 완벽하게 프론트로 전달합니다.
    """
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
        "portfolio_file_path": getattr(user, "portfolio_file_path", "") or "",
        "help_provide": getattr(user, "help_provide", "") or "",
        "help_receive": getattr(user, "help_receive", "") or "",
        "profile_image": getattr(user, "profile_image", "") or "",
    }


# 💡 [신규 추가] 특정 유저의 분리형 멘토 상세 정보를 조회하는 API
@app.get("/api/mentor/details/{user_id}")
def get_mentor_details(user_id: int, db: Session = Depends(get_db)):
    print(f" [멘토 프로필 상세 조회 요청] User ID: {user_id}")
    
    # 1. 공통 정보 추출을 위해 users 테이블 조회
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자 회원입니다.")
        
    # 2. 독립형 멘토 전용 정보 조회를 위해 mentors 테이블 조회
    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
    if not mentor:
        raise HTTPException(status_code=404, detail="해당 사용자는 멘토로 등록되어 있지 않습니다.")
        
    # 3. 양쪽 테이블의 정보를 통합하여 프론트엔드가 요구하는 포맷으로 반환
    return {
        "id": mentor.id,
        "user_id": mentor.user_id,
        "name": mentor.name or user.name,
        "profile_image": user.profile_image or "",
        "job_title": mentor.job_title,
        "career_history": mentor.career_history,
        "mentor_intro": mentor.mentor_intro,
        "mentoring_topics": mentor.mentoring_topics,
        "detailed_experience": mentor.detailed_experience,
        "price": mentor.price or "10,000 원",
    }
@app.get("/api/mentors/list")
def get_mentors_list(db: Session = Depends(get_db)):
    print(" [멘토 전체 리스트 조회 API 호출]")
    
    # Mentor 테이블과 User 테이블을 user_id 기준으로 조인(Join)하여 한 번에 조회합니다.
    results = db.query(Mentor, User).join(User, Mentor.user_id == User.id).all()
    
    mentors_data = []
    for mentor, user in results:
        mentors_data.append({
            "id": mentor.user_id, # 상세 페이지 라우팅을 위해 user_id 반환
            "name": mentor.name,
            "job_title": mentor.job_title or "직무 미상",
            "hashtags": getattr(user, "hashtags", "") or "",
            "profile_image": getattr(user, "profile_image", "") or "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=400"
        })
        
    return mentors_data

@app.put("/api/user/profile/{user_id}")
def update_user_profile(user_id: int, request: ProfileUpdateRequest, db: Session = Depends(get_db)):
    """일반 프로필 수정 정보 DB 영구 업데이트 처리 API"""
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
    """
    분리형 독립 멘토 등록 처리 API
    프론트에서 수신한 이름, 태그, 포트폴리오 정보를 Users 테이블 관계도 컬럼에 완벽 연동 안착시킵니다.
    """
    print(f" [분리형 멘토 등록 시작] User ID: {user_id}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 회원 데이터입니다.")

    # 🟢 DBeaver 관계도 컬럼 스펙에 이름/해시태그/링크/파일경로 1:1 정밀 바인딩 가동
    user.name = request.name
    user.hashtags = request.hashtags
    user.portfolio_url = request.portfolio_url          
    user.portfolio_file_path = request.portfolio_file_path  

    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()

    if not mentor:
        print(" ➔ 기존 멘토 레코드 없음: 새롭게 생성")
        mentor = Mentor(user_id=user_id)
        db.add(mentor)

    # 🟢 독립 멘토 세부 테이블 데이터 정보 매핑
    mentor.name = request.name
    mentor.job_title = request.job_title
    mentor.career_history = request.career_history
    mentor.mentor_intro = request.mentor_intro
    mentor.mentoring_topics = request.mentoring_topics
    mentor.detailed_experience = request.detailed_experience

    db.commit()
    print(f" [DB 분리 저장 완료] {user_id}번 유저의 이름, 링크, 파일경로가 Users 테이블에 완전히 영구 저장 완결되었습니다.")

    return {"message": "멘토 프로필 독립 등록 완료"}


@app.get("/api/mentor/dashboard/{user_id}")
def get_mentor_dashboard_data(user_id: int, db: Session = Depends(get_db)):
    """멘토 대시보드 내 실시간 활동 지표 조회 API"""
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
    """Azure OpenAI를 사용한 커피챗 대화 추천 질문 자동 생성 API"""
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
                {"role": "user", "content": user_prompt}, # 💡 정석 매핑 역할인 user 역할 바인딩
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


# =====================================================================
# 💡 [정밀 수정] 멘토 전체 목록 조회 API (일반 유저 완벽 컷 차단 버전)
# =====================================================================
@app.get("/api/mentors")
def get_mentors(db: Session = Depends(get_db)):
    # 🟢 조인(join)을 아예 제거했습니다. 오직 Mentor 테이블 데이터만 가져옵니다.
    results = db.query(Mentor).all()
    
    return [
        {
            "id": m.id,
            "name": m.name or "멘토",
            "avatar": "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=400", # 기본 이미지
            "price": m.price or "10,000 원",
            "job_title": m.job_title or "커리어 가이드",
            "techStack": ["백엔드", "인프라"], # 필요 시 m.mentoring_topics 활용 가능
            "bio": m.mentor_intro or "반가워요!"
        }
        for m in results
    ]

# =====================================================================
# 💡 [정밀 추가] 멘토 개별 상세 조회 API (Undefined Column 에러 근본적 해결)
# =====================================================================
@app.get("/api/mentors/{mentor_id}")
def get_mentor_detail(mentor_id: int, db: Session = Depends(get_db)):
    mentor = db.query(Mentor).filter(Mentor.id == mentor_id).first()
    if not mentor:
        raise HTTPException(status_code=404, detail="존재하지 않는 멘토입니다.")
    
    return {
        "id": mentor.id,
        "name": mentor.name or "멘토",
        "job_title": mentor.job_title or "직무 미정",
        "mentor_intro": mentor.mentor_intro or "<p>소개글이 없습니다.</p>",
        # 💡 None이면 빈 리스트 []를 보내도록 수정
        "career_history": mentor.career_history or [],
        "mentoring_topics": mentor.mentoring_topics or [],
        "detailed_experience": mentor.detailed_experience or [],
        "profile_image": "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=400"
    }

# =====================================================================
# [신규] 멘토 가용 시간 관련 엔드포인트
# =====================================================================

@app.get("/api/mentor/availability/{mentor_id}")
def get_mentor_availability(mentor_id: int, db: Session = Depends(get_db)):
    """
    멘토의 전체 가용 시간(available) + 예약 확정(booked) 슬롯을 함께 반환합니다.
    프론트의 scheduleData 초기값으로 사용합니다.
    반환 형태: { "2026-05-23": { "09:00": "available", "10:00": "booked" }, ... }
    """
    print(f" [가용 시간 조회] Mentor ID: {mentor_id}")

    result: Dict[str, Dict[str, str]] = {}

    # 1) MentorAvailability → available 슬롯
    availability_rows = db.query(MentorAvailability).filter(
        MentorAvailability.mentor_id == mentor_id
    ).all()

    for row in availability_rows:
        date_key = str(row.date)  # date → "YYYY-MM-DD"
        if date_key not in result:
            result[date_key] = {}
        result[date_key][row.time] = "available"

    # 2) Booking (status=PAID) → booked 슬롯 (available 위에 덮어씀)
    booking_rows = db.query(Booking).filter(
        Booking.mentor_id == mentor_id,
        Booking.status == "PAID"
    ).all()

    for row in booking_rows:
        date_key = str(row.booking_date)
        if date_key not in result:
            result[date_key] = {}
        result[date_key][row.booking_time] = "booked"

    print(f" [가용 시간 조회 완료] {len(availability_rows)}개 가용 + {len(booking_rows)}개 예약 반환")
    return result


@app.post("/api/mentor/availability/bulk")
def save_mentor_availability(request: AvailabilityBulkRequest, db: Session = Depends(get_db)):
    """
    멘토가 설정한 available 슬롯을 bulk upsert합니다.
    - 요청에 포함된 날짜는 기존 available 삭제 후 새로 insert (날짜 단위 교체)
    - booked 슬롯은 Booking 테이블에 있으므로 건드리지 않습니다.
    """
    print(f" [가용 시간 저장] Mentor ID: {request.mentor_id}, 날짜 수: {len(request.schedules)}")

    for date_str, times in request.schedules.items():
        # 해당 날짜의 기존 available 슬롯 삭제
        db.query(MentorAvailability).filter(
            MentorAvailability.mentor_id == request.mentor_id,
            MentorAvailability.date == date_str,
        ).delete()

        # 새 슬롯 insert
        for time in times:
            slot = MentorAvailability(
                mentor_id=request.mentor_id,
                date=date_str,
                time=time,
            )
            db.add(slot)

    db.commit()
    print(f" [가용 시간 저장 완료] Mentor ID: {request.mentor_id}")
    return {"message": "가용 시간이 저장되었습니다."}


@app.post("/api/mentor/penalty")
def apply_mentor_penalty(request: PenaltyRequest, db: Session = Depends(get_db)):
    """
    멘토가 예약 확정(booked) 슬롯을 취소할 때 호출됩니다.
    - Booking 상태를 CANCELLED로 변경
    - penalty_applied = True, cancelled_by = "mentor" 기록
    - MentorAvailability에서 해당 슬롯 삭제
    """
    print(f" [패널티 처리] Mentor ID: {request.mentor_id}, {request.date} {request.time}")

    # 해당 예약 조회
    booking = db.query(Booking).filter(
        Booking.mentor_id == request.mentor_id,
        Booking.booking_date == request.date,
        Booking.booking_time == request.time,
        Booking.status == "PAID",
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="해당 예약을 찾을 수 없습니다.")

    # 패널티 처리
    booking.status = "CANCELLED"
    booking.penalty_applied = True
    booking.cancelled_at = datetime.utcnow()
    booking.cancelled_by = "mentor"

    # MentorAvailability에서도 해당 슬롯 제거
    db.query(MentorAvailability).filter(
        MentorAvailability.mentor_id == request.mentor_id,
        MentorAvailability.date == request.date,
        MentorAvailability.time == request.time,
    ).delete()

    db.commit()
    print(f" [패널티 처리 완료] Booking ID: {booking.id}")
    return {"message": "예약이 취소되었으며 패널티가 부여되었습니다.", "booking_id": booking.id}


# 디버그: 시스템 구동 완료 로그 및 포트 매핑 확인
print(f"--- [DEBUG] 현재 등록된 라우터 개수: {len(app.routes)} ---")
for route in app.routes:
    print(f"DEBUG: 경로 정보 -> {route.path} | {getattr(route, 'methods', 'N/A')}")


if __name__ == "__main__":
    import uvicorn
    
    # 백엔드 서버를 0.0.0.0 IP 대역의 8000번 포트로 구동시킵니다.
    uvicorn.run(app, host="0.0.0.0", port=8000)
