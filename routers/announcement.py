import math
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from models import Announcement, User, UserRole, get_db
from auth import get_current_user # 기존 인증 함수

router = APIRouter(prefix="/api/announcements", tags=["announcements"])

# 💡 POST, PUT 요청의 JSON 데이터를 받기 위한 Pydantic 모델
class AnnouncementCreate(BaseModel):
    title: str
    content: str


# ==========================================
# 1. 공지사항 조회 (전체 페이지 수 포함 + 최신순 정렬)
# ==========================================
@router.get("")
def get_announcements(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    # 1. 전체 공지사항 개수 파악
    total_count = db.query(Announcement).count()
    
    # 2. 전체 페이지 수 계산 (예: 21개고 limit이 10이면 3페이지)
    total_pages = math.ceil(total_count / limit) if total_count > 0 else 1
    
    # 3. 최신 글이 맨 위에 오도록 내림차순(.desc()) 정렬 후 페이징
    announcements = db.query(Announcement).order_by(Announcement.id.desc()).offset(skip).limit(limit).all()
    
    # 4. 프론트엔드가 요구하는 형식으로 묶어서 반환
    return {
        "items": announcements,
        "total_pages": total_pages
    }


# ==========================================
# 2. 공지사항 작성 (관리자 전용, JSON 바디 수신)
# ==========================================
@router.post("")
def create_announcement(request: AnnouncementCreate, 
                        db: Session = Depends(get_db), 
                        current_user: User = Depends(get_current_user)):
    # 관리자 여부 체크 (UserRole.ADMIN 또는 문자열 "ADMIN" 대응)
    if current_user.role not in [UserRole.ADMIN, "ADMIN", "admin"]:
        raise HTTPException(status_code=403, detail="관리자 전용 기능입니다.")
    
    # JSON으로 받은 데이터를 기반으로 생성
    new_notice = Announcement(
        title=request.title, 
        content=request.content, 
        author_id=current_user.id
    )
    db.add(new_notice)
    db.commit()
    return {"message": "공지사항 등록 완료"}


# ==========================================
# 3. 공지사항 삭제 (관리자 전용) - 새로 추가됨!
# ==========================================
@router.delete("/{notice_id}")
def delete_announcement(notice_id: int, 
                        db: Session = Depends(get_db), 
                        current_user: User = Depends(get_current_user)):
    # 관리자 여부 체크
    if current_user.role not in [UserRole.ADMIN, "ADMIN", "admin"]:
        raise HTTPException(status_code=403, detail="관리자 전용 기능입니다.")
    
    # 지우려는 공지사항이 DB에 있는지 확인
    notice = db.query(Announcement).filter(Announcement.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="해당 공지사항을 찾을 수 없습니다.")
    
    db.delete(notice)
    db.commit()
    return {"message": "공지사항이 삭제되었습니다."}