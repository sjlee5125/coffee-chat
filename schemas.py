from pydantic import BaseModel
from typing import Optional, Dict, List
from datetime import date

# ─── [일반 유저 관련 스키마] ───

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
    name: Optional[str] = None
    bio: Optional[str] = None
    mbti: Optional[str] = None
    portfolio_url: Optional[str] = None
    profile_image: Optional[str] = None
    phone_number: Optional[str] = None
    
    # 일반 프로필 4인방
    hashtags: Optional[str] = None
    experience: Optional[str] = None
    help_provide: Optional[str] = None
    help_receive: Optional[str] = None
    
    # 직무 및 상태
    main_category: Optional[str] = None
    sub_category: Optional[str] = None
    status: Optional[str] = None

    # 호스트(멘토) 프로필 데이터들
    job_title: Optional[str] = None
    career_history: Optional[str] = None
    mentor_intro: Optional[str] = None
    mentoring_topics: Optional[str] = None
    detailed_experience: Optional[str] = None
    
    # 🚀 방금 추가된 대화 키워드와 링크까지 완벽 허용!
    mentor_keywords: Optional[str] = None
    mentor_links: Optional[str] = None
# ─── [멘토 관련 스키마] ───

class MentorRegisterRequest(BaseModel):
    """
    멘토 프로필 독립 등록/수정 시 프론트엔드에서 수신할 요청 가방 데이터 명세
    DBeaver 데이터베이스 엔티티 관계도 스펙과 1:1 완벽 맵핑 설계
    """
    name: str
    status: str             # 추가
    main_category: str      # 추가
    sub_category: str       # 추가
    job_title: str
    career_history: Optional[str] = None
    mentor_intro: Optional[str] = None
    mentoring_topics: Optional[str] = None
    detailed_experience: Optional[str] = None
    hashtags: Optional[str] = None
    portfolio_url: Optional[str] = None
    portfolio_file_path: Optional[str] = None  # attachedFiles 첨부파일명 저장용 칸


class AvailabilityBulkRequest(BaseModel):
    """멘토 가용 시간 bulk 저장 요청 명세"""
    mentor_id: int
    schedules: Dict[str, List[str]]  # { "2026-05-23": ["09:00", "09:30"], ... }


# ─── [예약 및 기능 관련 스키마] ───

class BookingCreateRequest(BaseModel):
    """예약 생성 요청 데이터 명세"""
    mentorId: int
    userId: int
    date: date
    time: str
    questions: str


class PenaltyRequest(BaseModel):
    """멘토 귀책 예약 취소(패널티) 처리 요청 명세"""
    mentor_id: int
    date: str   # "2026-05-23"
    time: str   # "09:00"
    reason: str


class AIQuestionRequest(BaseModel):
    """AI 질문 추천 어시스턴트 요청 시 수신할 메모 명세"""
    memo: str