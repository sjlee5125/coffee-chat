import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import User, Mentor, get_db
from schemas import ProfileUpdateRequest

router = APIRouter(
    prefix="/api/user",
    tags=["Users"]
)

@router.get("/{user_id}")
def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
    """일반 프로필 + 호스트(멘토) 프로필 통합 교차 조회 API"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")

    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()

    # 멘토 자기소개 연동 기본값 처리
    m_intro = mentor.mentor_intro if (mentor and mentor.mentor_intro) else (user.bio or "")
    
    # 멘토 해시태그 연동 기본값 처리
    m_topics = "[]"
    if mentor and mentor.mentoring_topics and mentor.mentoring_topics != "[]":
        m_topics = mentor.mentoring_topics
    elif user.hashtags:
        tags = [t.strip() for t in user.hashtags.split() if t.strip()]
        m_topics = json.dumps(tags)

    # 멘토 링크 연동 기본값 처리
    m_links = "[]"
    if mentor and hasattr(mentor, "mentor_links") and mentor.mentor_links:
        m_links = mentor.mentor_links
    elif user.portfolio_url:
        m_links = json.dumps([user.portfolio_url])

    # 💡 [추가] 대화 키워드 안전하게 가져오기
    m_keywords = "[]"
    if mentor and hasattr(mentor, "mentor_keywords") and mentor.mentor_keywords:
        m_keywords = mentor.mentor_keywords

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "bio": user.bio or "",
        "mbti": user.mbti or "",
        "hashtags": user.hashtags or "",
        "experience": user.experience or "",
        "portfolio_url": user.portfolio_url or "",
        "portfolio_file_path": user.portfolio_file_path or "",
        "help_provide": user.help_provide or "",
        "help_receive": user.help_receive or "",
        "profile_image": user.profile_image or "",
        "phone_number": user.phone_number or "", 
        
        # 🌟 호스트 화면으로 꼽아줄 데이터들 완벽 조회
        "job_title": mentor.job_title if mentor else "",
        "mentor_intro": m_intro,
        "career_history": mentor.career_history if mentor else "[]",
        "mentoring_topics": m_topics,
        "detailed_experience": mentor.detailed_experience if mentor else "[]",
        "mentor_keywords": m_keywords,  # 💡 이제 새로고침해도 대화 키워드 잘 뜹니다!
        "mentor_links": m_links 
    }


@router.put("/profile/{user_id}")
def update_user_profile(user_id: int, request: ProfileUpdateRequest, db: Session = Depends(get_db)):
    """일반 프로필 및 호스트 프로필 DB 통합 영구 저장 처리 API"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")

    # 1. 일반 프로필 테이블 저장
    user.name = request.name
    user.bio = request.bio
    user.mbti = request.mbti
    user.hashtags = request.hashtags
    user.experience = request.experience
    user.portfolio_url = request.portfolio_url
    user.help_provide = request.help_provide
    user.help_receive = request.help_receive
    user.phone_number = request.phone_number 
    
    if request.profile_image:
        user.profile_image = request.profile_image

    # 2. 호스트(멘토) 프로필 테이블 저장
    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
    if not mentor:
        mentor = Mentor(user_id=user_id)
        db.add(mentor)

    # 🌟 [핵심 수리] 프론트엔드가 보낸 멘토 데이터들을 DB 객체에 꽉꽉 채워 넣습니다!
    mentor.name = request.name
    mentor.job_title = request.job_title if request.job_title else "직무 미정"
    mentor.mentor_intro = request.mentor_intro if request.mentor_intro else request.bio
    mentor.career_history = request.career_history if request.career_history else "[]"
    mentor.detailed_experience = request.detailed_experience if request.detailed_experience else "[]"
    
    # 해시태그 안전 동기화
    if request.mentoring_topics and request.mentoring_topics != "[]":
        mentor.mentoring_topics = request.mentoring_topics
    elif request.hashtags:
        tags = [t.strip() for t in request.hashtags.split() if t.strip()]
        mentor.mentoring_topics = json.dumps(tags)

    # 💡 DB 모델 컬럼 유연성 확보 (에러 방지용 안전 장치)
    if hasattr(mentor, "mentor_keywords") and request.mentor_keywords:
        mentor.mentor_keywords = request.mentor_keywords
    if hasattr(mentor, "mentor_links") and request.mentor_links:
        mentor.mentor_links = request.mentor_links

    db.commit()
    return {"message": "프로필 정보가 성공적으로 바인딩되었습니다."}