import json
from fastapi import APIRouter, Depends, HTTPException
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from models import User, Mentor, get_db
from schemas import ProfileUpdateRequest
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")

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
    is_mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first() is not None
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
        "mentor_links": m_links ,
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
        "is_mentor": is_mentor
    }
@router.post("/{user_id}/profile-image")
async def upload_profile_image(
    user_id: int, 
    file: UploadFile = File(...), 
    db: Session = Depends(get_db)
):
    """유저의 프로필 이미지를 Azure에 업로드하고 DB에 URL을 저장합니다."""
    
    # 1. 설정 및 유저 확인
    if not AZURE_CONNECTION_STRING or not AZURE_CONTAINER_NAME:
        raise HTTPException(status_code=500, detail="Azure Storage 설정 오류")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다.")

    try:
        # 2. 고유한 파일명 생성 (예: user_2_a1b2c3d4.png)
        file_extension = file.filename.split(".")[-1]
        unique_filename = f"user_{user_id}_{uuid.uuid4().hex[:8]}.{file_extension}"

        # 3. Azure 연결 및 업로드
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        blob_client = blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=unique_filename)

        contents = await file.read()
        blob_client.upload_blob(contents, overwrite=True)

        # 4. DB에 주소(URL) 저장
        image_url = blob_client.url
        user.profile_image = image_url
        db.commit()
        db.refresh(user)

        return {
            "message": "프로필 이미지가 성공적으로 업로드되었습니다.", 
            "profile_image": image_url
        }

    except Exception as e:
        print(f"❌ [Azure 업로드 에러]: {str(e)}")
        raise HTTPException(status_code=500, detail="이미지 업로드에 실패했습니다.")

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

    if hasattr(request, 'phone_number'):
            user.phone_number = request.phone_number
    db.commit()
    return {"message": "프로필 정보가 성공적으로 바인딩되었습니다."}