import os
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

from models import User, Mentor, get_db
from schemas import ProfileUpdateRequest

# 환경변수 로드
load_dotenv()
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")

# 라우터 생성
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

    # 대화 키워드 안전하게 가져오기
    m_keywords = "[]"
    if mentor and hasattr(mentor, "mentor_keywords") and mentor.mentor_keywords:
        m_keywords = mentor.mentor_keywords
        
    is_mentor = mentor is not None

    # 🌟 [교차 복구 안전장치] 만약 User나 Mentor 테이블 한쪽에만 파일 경로가 있고 다른 쪽에 비어 있다면 상호 동기화 유추
    final_file_path = user.portfolio_file_path or ""
    if not final_file_path and mentor and hasattr(mentor, "portfolio_file_path") and mentor.portfolio_file_path:
        final_file_path = mentor.portfolio_file_path

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "bio": user.bio or "",
        "mbti": user.mbti or "",
        "hashtags": user.hashtags or "",
        "experience": user.experience or "",
        "portfolio_url": user.portfolio_url or "",
        
        # 🌟 상호 보완된 통합 파일 경로 반환 처리로 화면 소멸 방지
        "portfolio_file_path": final_file_path,
        
        "help_provide": user.help_provide or "",
        "help_receive": user.help_receive or "",
        "profile_image": user.profile_image or "",
        "phone_number": user.phone_number or "", 
        
        "main_category": getattr(mentor, "main_category", "") if mentor else "",
        "sub_category": getattr(mentor, "sub_category", "") if mentor else "",
        "status": getattr(mentor, "status", "") if mentor else "",
        
        "job_title": mentor.job_title if mentor else "",
        "mentor_intro": m_intro,
        "career_history": mentor.career_history if mentor else "[]",
        "mentoring_topics": m_topics,
        "detailed_experience": mentor.detailed_experience if mentor else "[]",
        "mentor_keywords": m_keywords, 
        "mentor_links": m_links,
        "is_mentor": is_mentor
    }
@router.post("/{user_id}/profile-image")
async def upload_profile_image(
    user_id: int, 
    file: UploadFile = File(...), 
    db: Session = Depends(get_db)
):
    """유저의 프로필 이미지를 Azure에 업로드하고 DB에 URL을 저장합니다."""
    
    if not AZURE_CONNECTION_STRING or not AZURE_CONTAINER_NAME:
        raise HTTPException(status_code=500, detail="Azure Storage 설정 오류")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다.")

    try:
        file_extension = file.filename.split(".")[-1]
        unique_filename = f"user_{user_id}_{uuid.uuid4().hex[:8]}.{file_extension}"

        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        blob_client = blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=unique_filename)

        contents = await file.read()
        blob_client.upload_blob(contents, overwrite=True)

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
    
    # 🌟 User 테이블 기입 보장
    user.portfolio_file_path = request.portfolio_file_path

    if request.profile_image and request.profile_image.startswith("http"):
        user.profile_image = request.profile_image

    # 2. 호스트(멘토) 프로필 테이블 저장
    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()
    if not mentor:
        mentor = Mentor(user_id=user_id)
        db.add(mentor)

    if hasattr(request, "main_category"):
        mentor.main_category = request.main_category
    if hasattr(request, "sub_category"):
        mentor.sub_category = request.sub_category
    if hasattr(request, "status"):
        mentor.status = request.status

    mentor.name = request.name
    mentor.job_title = request.job_title if request.job_title else "직무 미정"
    mentor.mentor_intro = request.mentor_intro if request.mentor_intro else request.bio
    mentor.career_history = request.career_history if request.career_history else "[]"
    mentor.detailed_experience = request.detailed_experience if request.detailed_experience else "[]"
    
    # 🌟🌟🌟 [양방향 동기화] 만약 Mentor 모델 명세에 동일한 파일 경로 컬럼이 설계되어 있다면 동시 기입
    if hasattr(mentor, "portfolio_file_path"):
        mentor.portfolio_file_path = request.portfolio_file_path

    if request.mentoring_topics and request.mentoring_topics != "[]":
        mentor.mentoring_topics = request.mentoring_topics
    elif request.hashtags:
        tags = [t.strip() for t in request.hashtags.split() if t.strip()]   
        mentor.mentoring_topics = json.dumps(tags)

    if hasattr(request, "mentor_keywords") and request.mentor_keywords:
        mentor.mentor_keywords = request.mentor_keywords
    else:
        mentor.mentor_keywords = "[]"

    if hasattr(request, "mentor_links") and request.mentor_links:
        mentor.mentor_links = request.mentor_links
    else:
        mentor.mentor_links = "[]"

    db.commit()
    return {"message": "프로필 정보가 성공적으로 바인딩되었습니다."}
@router.post("/upload/portfolio")
async def upload_portfolio(file: UploadFile = File(...)):
    """포트폴리오 파일을 Azure 'portfoliofile' 컨테이너에 업로드하고 URL을 반환합니다."""
    
    if not AZURE_CONNECTION_STRING:
        raise HTTPException(status_code=500, detail="Azure Storage 설정 오류")

    try:
        # 🌟 요청하신 포트폴리오 전용 컨테이너 이름
        PORTFOLIO_CONTAINER = "portfoliofile"

        # 파일명 중복 방지를 위한 UUID 추가
        file_extension = file.filename.split(".")[-1]
        unique_filename = f"portfolio_{uuid.uuid4().hex[:8]}.{file_extension}"

        # Azure 접속 및 컨테이너 객체 생성
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(PORTFOLIO_CONTAINER)
        
        # 만약 portfoliofile 컨테이너가 없다면 자동으로 만들어줍니다
        if not container_client.exists():
            container_client.create_container()

        # 업로드 준비
        blob_client = container_client.get_blob_client(unique_filename)
        contents = await file.read()
        
        # 🚀 Azure에 실제 파일 업로드!
        blob_client.upload_blob(contents, overwrite=True)

        # 업로드된 최종 URL 가져오기
        file_url = blob_client.url

        # 프론트엔드로 URL 리턴
        return {
            "message": "포트폴리오 파일이 성공적으로 업로드되었습니다.", 
            "url": file_url
        }

    except Exception as e:
        print(f"❌ [Azure 포트폴리오 업로드 에러]: {str(e)}")
        raise HTTPException(status_code=500, detail="포트폴리오 업로드에 실패했습니다.")