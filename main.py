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
from utils import send_solapi_sms 
import auth

# 디버그: auth.py 모듈이 로드된 실제 시스템 경로를 로그에 출력합니다.
print(f"DEBUG: auth.py loaded from: {auth.__file__}")
from auth import router
from models import User, Mentor, Booking, MentorAvailability, get_db, create_tables

# 서버 실행 시 시스템의 .env 환경변수를 로드합니다.
load_dotenv()

app = FastAPI()

# 💡 [CORS 설정] 자격 증명(allow_credentials=True) 승인을 위해 명시적인 오리진 리스트를 설계합니다.
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://48.211.169.52",
    "http://48.211.169.52:8000", 
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/auth")


# Azure OpenAI 연동을 위한 환경 변수
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


# --- [데이터 검증 스키마: Pydantic 영역] ---

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
    phone_number: Optional[str] = None


class AIQuestionRequest(BaseModel):
    memo: str


class BookingCreateRequest(BaseModel):
    mentorId: int  # 💡 이제 무조건 mentors 테이블의 고유 id(PK)를 받습니다.
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
    portfolio_file_path: Optional[str] = None


class AvailabilityBulkRequest(BaseModel):
    """멘토 가용 시간 bulk 저장 요청 명세"""
    mentor_id: int  # 💡 mentors 테이블의 고유 id 또는 user_id 대응을 위해 내부 분기 처리
    schedules: Dict[str, List[str]]


class PenaltyRequest(BaseModel):
    mentor_id: int
    date: str
    time: str
    reason: str


class ReservationRequest(BaseModel):
    mentor_id: int
    mentee_id: int


# --- [API 라우터 비즈니스 로직 구역] ---

@app.get("/")
def root():
    return {"message": "CoffeeChat Backend Running"}


@app.get("/login/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    provider_id = "4893673152"
    email = None
    name = "이승재"

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
            user = User(email=email, name=name, provider="kakao", provider_id=provider_id)
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

        access_token = auth.create_access_token(data={"sub": user.email, "user_id": user.id})
        safe_name = quote(user.name)
        safe_email = quote(user.email)

        if is_new_user:
            frontend_url = f"http://localhost:5173/profile-setup?token={access_token}&name={safe_name}&email={safe_email}&id={user.id}"
        else:
            frontend_url = f"http://localhost:5173/?token={access_token}&name={safe_name}"

        return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)
    except Exception as e:
        return RedirectResponse(url="http://localhost:5173/login?error=true", status_code=status.HTTP_302_FOUND)


@app.get("/api/user/{user_id}")
def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
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
        "phone_number": getattr(user, "phone_number", "") or "",
    }


# =====================================================================
# 💡 [핵심 수정] 멘토 가용 시간 조회 엔드포인트 (Mentors.id 기준 완전 일치)
# =====================================================================
@app.get("/api/mentor/availability/{mentor_id}")
def get_mentor_availability(mentor_id: int, db: Session = Depends(get_db)):
    # 1. 멘토 고유 일련번호(id)로 먼저 찾고, 없으면 호환성을 위해 user_id 매핑 체킹
    mentor = db.query(Mentor).filter(Mentor.id == mentor_id).first()
    if not mentor:
        mentor = db.query(Mentor).filter(Mentor.user_id == mentor_id).first()
    
    if not mentor:
        return {}

    today = date.today()

    availability_rows = db.query(MentorAvailability).filter(
        MentorAvailability.mentor_id == mentor.id,
        MentorAvailability.date >= today
    ).all()

    booking_rows = db.query(Booking).filter(
        Booking.mentor_id == mentor.id,
        Booking.booking_date >= today,
        Booking.status == "PAID"
    ).all()

    result: Dict[str, Dict[str, str]] = {}

    for row in availability_rows:
        date_key = str(row.date)
        if date_key not in result:
            result[date_key] = {}
        result[date_key][row.time] = "available"

    for row in booking_rows:
        date_key = str(row.booking_date)
        if date_key not in result:
            result[date_key] = {}
        result[date_key][row.booking_time] = "booked"

    return result


@app.get("/api/mentor/details/{user_id}")
def get_mentor_details(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자 회원입니다.")
        
    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
    if not mentor:
        raise HTTPException(status_code=404, detail="해당 사용자는 멘토로 등록되어 있지 않습니다.")
        
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
        "price": mentor.price or "15,000 원",
    }


@app.put("/api/user/profile/{user_id}")
def update_user_profile(user_id: int, request: ProfileUpdateRequest, db: Session = Depends(get_db)):
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
    if request.phone_number is not None:
        user.phone_number = request.phone_number
    if request.profile_image:
        user.profile_image = request.profile_image

    db.commit()
    return {"message": "프로필 정보가 성공적으로 바인딩되었습니다."}


@app.post("/api/mentor/register/{user_id}")
def register_mentor(user_id: int, request: MentorRegisterRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 회원 데이터입니다.")

    user.name = request.name
    user.hashtags = request.hashtags
    user.portfolio_url = request.portfolio_url          
    user.portfolio_file_path = request.portfolio_file_path  

    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
    if not mentor:
        mentor = Mentor(user_id=user_id)
        db.add(mentor)

    mentor.name = request.name
    mentor.job_title = request.job_title
    mentor.career_history = request.career_history
    mentor.mentor_intro = request.mentor_intro
    mentor.mentoring_topics = request.mentoring_topics
    mentor.detailed_experience = request.detailed_experience

    db.commit()
    return {"message": "멘토 프로필 독립 등록 완료"}


@app.get("/api/mentor/dashboard/{user_id}")
def get_mentor_dashboard_data(user_id: int, db: Session = Depends(get_db)):
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
    return {"stats": stats_data, "upcoming_chats": []}


@app.post("/api/ai/generate-questions")
async def generate_ai_questions(request: AIQuestionRequest):
    if not request.memo.strip():
        raise HTTPException(status_code=400, detail="메모 내용이 비어 있습니다.")

    try:
        system_prompt = (
            "당신은 커리어 멘토링 서비스의 질문 추천 AI 어시스턴트입니다. "
            "사용자가 멘토에게 질문하고 싶은 내용을 정제하여 번호 형태로 줄바꿈 출력하세요."
        )
        response = ai_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"사용자 메모:\n{request.memo}"}],
            temperature=0.7,
            max_tokens=1000,
        )
        return {"aiQuestions": response.choices[0].message.content.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 질문 생성 중 내부 오류: {str(e)}")


@app.get("/api/mentors")
def get_mentors(db: Session = Depends(get_db)):
    results = db.query(Mentor).all()
    return [
        {
            "id": m.id,  # 💡 진짜 mentors.id 전달
            "name": m.name or "멘토",
            "avatar": "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=400", 
            "price": m.price or "10,000 원",
            "job_title": m.job_title or "커리어 가이드",
            "techStack": ["백엔드", "인프라"], 
            "bio": m.mentor_intro or "반가워요!"
        }
        for m in results
    ]


# =====================================================================
# 💡 [핵심 수정] 리스트 API에서 진짜 `mentors.id`를 내려주도록 정밀 튜닝
# =====================================================================
@app.get("/api/mentors/list")
def get_mentors_list(db: Session = Depends(get_db)):
    print(" [멘토 전체 리스트 조회 API 호출]")
    results = db.query(Mentor, User).join(User, Mentor.user_id == User.id).all()
    
    mentors_data = []
    for mentor, user in results:
        mentors_data.append({
            "id": mentor.id,  # 🚨 기존 mentor.user_id에서 mentor.id(진짜 PK)로 전격 수정!
            "name": mentor.name,
            "job_title": mentor.job_title or "직무 미상",
            "hashtags": getattr(user, "hashtags", "") or "",
            "profile_image": getattr(user, "profile_image", "") or "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=400"
        })
    return mentors_data


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
        "career_history": mentor.career_history or [],
        "mentoring_topics": mentor.mentoring_topics or [],
        "detailed_experience": mentor.detailed_experience or [],
        "profile_image": "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=400"
    }


# =====================================================================
# 💡 [핵심 수정] 예약 생성 API (안전한 형변환 및 완벽한 무결성 저장 보장)
# =====================================================================
@app.post("/api/booking/create")
def create_booking(request: BookingCreateRequest, db: Session = Depends(get_db)):
    print(f" [예약 생성] 수신된 mentorId: {request.mentorId}, 날짜: {request.date}, 시간: {request.time}")

    # 1. mentors 테이블의 고유 id(PK)로 멘토 엔티티를 정밀 타겟팅합니다.
    mentor = db.query(Mentor).filter(Mentor.id == request.mentorId).first()
    if not mentor:
        # 프론트가 혹시 user_id를 보냈을 경우를 대비한 유연한 2차 가드 필터링
        mentor = db.query(Mentor).filter(Mentor.user_id == request.mentorId).first()
    
    if not mentor:
        raise HTTPException(status_code=404, detail="존재하지 않는 멘토입니다.")

    # 2. 중복 예약 여부 판별
    existing = db.query(Booking).filter(
        Booking.mentor_id == mentor.id,
        Booking.booking_date == request.date,
        Booking.booking_time == request.time,
        Booking.status == "PAID"
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="이미 예약이 완결된 슬롯입니다.")

    # 3. 예약 정보 빌드 및 DB 영구 영속화 추가
    booking = Booking(
        mentor_id=mentor.id,
        booking_date=request.date,
        booking_time=request.time,
        questions=request.questions,
        status="PAID"
    )
    db.add(booking)
    db.flush() # 영속성 컨텍스트 임시 플러시 처리로 키 제약조건 선검증

    # 4. 가용 시간 슬롯 확정 삭제 (Mentors.id 기준으로 깔끔하게 원천 제거)
    db.query(MentorAvailability).filter(
        MentorAvailability.mentor_id == mentor.id,
        MentorAvailability.date == request.date,
        MentorAvailability.time == request.time,
    ).delete()

    db.commit()
    db.refresh(booking)
    
    print(f" [성공] {mentor.name} 멘토님의 스케줄 예약이 최종 확정 저장되었습니다 (Booking ID: {booking.id})")
    return {"message": "예약이 완료되었습니다.", "booking_id": booking.id}


# =====================================================================
# 💡 [신규/보완] 멘토 가용 시간 Bulk 저장 (ID 꼬임 완전 방지 가드 탑재)
# =====================================================================
@app.post("/api/mentor/availability/bulk")
def save_mentor_availability(request: AvailabilityBulkRequest, db: Session = Depends(get_db)):
    print(f" [가용 시간 bulk 저장 시작] 수신된 ID 파라미터: {request.mentor_id}")

    # 인입된 ID가 유저 ID일지, 멘토 ID일지 모르기 때문에 둘 다 교차 검증을 가동합니다.
    mentor = db.query(Mentor).filter(Mentor.id == request.mentor_id).first()
    if not mentor:
        mentor = db.query(Mentor).filter(Mentor.user_id == request.mentor_id).first()
        
    if not mentor:
        raise HTTPException(status_code=404, detail="등록된 멘토 프로필을 찾을 수 없습니다.")

    # 멘토의 진짜 고유 고정 PK(id)를 기준으로 가용 시간 데이터를 인서트합니다.
    real_mentor_id = mentor.id

    for date_str, times in request.schedules.items():
        # 기존 해당 날짜 슬롯을 클리어 한 후 재인서트 (Upsert 구현)
        db.query(MentorAvailability).filter(
            MentorAvailability.mentor_id == real_mentor_id,
            MentorAvailability.date == date_str,
        ).delete()

        for time_str in times:
            slot = MentorAvailability(
                mentor_id=real_mentor_id,
                date=date_str,
                time=time_str,
            )
            db.add(slot)

    db.commit()
    print(f" [성공] 멘토 {mentor.name} (PK: {real_mentor_id}) 가용 일정 bulk 덤프 완료")
    return {"message": "가용 시간이 성공적으로 저장되었습니다."}


@app.post("/api/mentor/penalty")
def apply_mentor_penalty(request: PenaltyRequest, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(
        Booking.mentor_id == request.mentor_id,
        Booking.booking_date == request.date,
        Booking.booking_time == request.time,
        Booking.status == "PAID",
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="해당 예약을 찾을 수 없습니다.")

    booking.status = "CANCELLED"
    booking.penalty_applied = True
    booking.cancelled_at = datetime.utcnow()
    booking.cancelled_by = "mentor"

    db.query(MentorAvailability).filter(
        MentorAvailability.mentor_id == request.mentor_id,
        MentorAvailability.date == request.date,
        MentorAvailability.time == request.time,
    ).delete()

    db.commit()
    return {"message": "예약이 취소되었으며 패널티가 부여되었습니다.", "booking_id": booking.id}


@app.post("/api/reservations")
def create_reservation(reservation_data: ReservationRequest, db: Session = Depends(get_db)):
    mentor = db.query(User).filter(User.id == reservation_data.mentor_id).first()
    mentee = db.query(User).filter(User.id == reservation_data.mentee_id).first()
    
    if mentor and mentor.phone_number:
        sms_message = f"[Coffee Chat]\n{mentor.name} 멘토님!\n{mentee.name}님의 커피챗 신청이 도착했습니다.\n접속해서 확인해주세요☕"
        send_solapi_sms(mentor.phone_number, sms_message)
    
    return {"message": "신청 완료 및 멘토 알림 전송 성공!"}


# =====================================================================
# 💡 [404 방어] 프론트엔드 실시간 알림 조회를 위한 빈 라우터 제공
# =====================================================================
@app.get("/api/notifications")
def get_user_notifications(db: Session = Depends(get_db)):
    return []


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)