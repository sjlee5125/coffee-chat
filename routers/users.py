from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import User, get_db
from schemas import ProfileUpdateRequest

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
    }


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

    db.commit()
    return {"message": "프로필 정보가 성공적으로 바인딩되었습니다."}