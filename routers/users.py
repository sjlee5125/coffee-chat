import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from models import User, get_db
from schemas import ProfileUpdateRequest
from azure.storage.blob import BlobServiceClient
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")
# 라우터 생성
router = APIRouter(
    prefix="/api/user",
    tags=["Users"]
)

@router.get("/{user_id}")
def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
    """일반 프로필 전체 데이터 조회 API"""
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
    """일반 프로필 수정 정보 DB 영구 업데이트 처리 API"""
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
    if hasattr(request, 'phone_number'):
            user.phone_number = request.phone_number
    db.commit()
    return {"message": "프로필 정보가 성공적으로 바인딩되었습니다."}