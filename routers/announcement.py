from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import Announcement, User, UserRole, get_db
from database import get_current_user # 기존 인증 함수

router = APIRouter(prefix="/api/announcements", tags=["announcements"])

# 1. 공지사항 조회 (페이지네이션 적용)
@router.get("")
def get_announcements(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    return db.query(Announcement).offset(skip).limit(limit).all()

# 2. 공지사항 작성 (관리자만)
@router.post("")
def create_announcement(title: str, content: str, 
                        db: Session = Depends(get_db), 
                        current_user: User = Depends(get_current_user)):
    # 여기서 관리자 여부 체크
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="관리자 전용 기능입니다.")
    
    new_notice = Announcement(title=title, content=content, author_id=current_user.id)
    db.add(new_notice)
    db.commit()
    return {"message": "공지사항 등록 완료"}