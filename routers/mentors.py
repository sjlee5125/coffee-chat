from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import Dict
from sqlalchemy import desc
from azure.storage.blob import BlobServiceClient, ContentSettings
import uuid
import os
from models import User, Mentor, Booking, MentorAvailability, get_db
from schemas import MentorRegisterRequest, AvailabilityBulkRequest, PenaltyRequest
from .matching import calc_match_score

router = APIRouter(tags=["Mentors"])


@router.get("/api/mentors/recommended")
async def get_recommended_mentors(user_id: int, db: Session = Depends(get_db)):
    try:
        current_user = db.query(User).filter(User.id == user_id).first()
        
        # 💡 [성능 최적화] User와 Mentor를 한 번의 쿼리로 JOIN해서 가져옵니다 (N+1 문제 해결)
        results = db.query(User, Mentor).join(Mentor, User.id == Mentor.user_id).filter(User.id != user_id).all()

        scored_mentors = []
        for user, m_info in results:
            # 🌟 [추천 로직 강화]
            # 멘티(current_user)의 "주요 이력 및 경력(experience)",
            # "도움을 줄 수 있는 분야(help_provide)", "배우고 싶은 분야(help_receive)"를
            # 멘토의 프로필(m_info: mentoring_topics/career_history/job_title 등)과
            # 함께 비교할 수 있도록 m_info(Mentor)를 같이 전달합니다.
            score, reasons = calc_match_score(current_user, user, m_info) if current_user else (0, [])
            
            # User 테이블에서 help_provide 데이터를 리스트로 파싱합니다.
            tech_stack = []
            if getattr(user, "help_provide", None):
                tech_stack = [tech.strip() for tech in user.help_provide.split(",") if tech.strip()]

            scored_mentors.append({
                "id": m_info.id,
                "mentor_id": m_info.id,
                "user_id": user.id,
                "name": user.name or "호스트",
                "bio": user.bio or "",
                "profile_image": user.profile_image or "",
                "hashtags": user.hashtags or "",
                "techStack": tech_stack, 
                "mentor_intro": m_info.mentor_intro,
                "job_title": m_info.job_title or "직무 미정",
                "main_category": m_info.main_category or "",
                "sub_category": m_info.sub_category or "",
                "status": m_info.status or "현직자",
                "mentor_keywords": m_info.mentoring_topics or "[]",
                "match_score": score,
                "match_reasons": reasons[:3],
            })

        scored_mentors.sort(key=lambda x: x["match_score"], reverse=True)
        return scored_mentors
    except Exception as e:
        print(f"🚨 get_recommended_mentors 에러: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/mentors")
def get_mentors(db: Session = Depends(get_db)):
    # 💡 [성능 최적화] Mentor와 User를 한 번의 쿼리로 JOIN해서 가져옵니다 (N+1 문제 해결)
    results = db.query(Mentor, User).join(User, Mentor.user_id == User.id).order_by(desc(Mentor.views)).all()
    
    mentors_data = []
    for m, user_info in results:
        profile_url = user_info.profile_image if user_info and user_info.profile_image else ""

        # User 테이블의 help_provide 데이터를 가져와 리스트 형태로 파싱
        tech_stack = []
        if user_info and getattr(user_info, "help_provide", None):
            tech_stack = [tech.strip() for tech in user_info.help_provide.split(",") if tech.strip()]

        mentors_data.append({
            "id": m.id,            
            "mentor_id": m.id,      
            "user_id": m.user_id,   
            "name": m.name or "호스트",
            "status": m.status or "현직자",
            "main_category": m.main_category or "",
            "sub_category": m.sub_category or "",
            "price": m.price or "10,000 원",
            "job_title": m.job_title or "커리어 가이드",
            "techStack": tech_stack, 
            "avatar": profile_url,
            "profile_image": profile_url,
            "bio": m.mentor_intro or "반가워요!",
            "views": m.views or 0,
        })
    return mentors_data


@router.get("/api/mentors/list")
def get_mentors_list(db: Session = Depends(get_db)):
    results = db.query(Mentor, User).join(User, Mentor.user_id == User.id).all()
    
    mentors_data = []
    for mentor, user in results:
        mentors_data.append({
            "id": mentor.id,            
            "mentor_id": mentor.id,     
            "user_id": mentor.user_id,  
            "name": mentor.name,
            "job_title": mentor.job_title or "직무 미상",
            "hashtags": getattr(user, "hashtags", "") or "",
            "profile_image": getattr(user, "profile_image", "") or "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=400"
        })
    return mentors_data


@router.get("/api/mentors/{mentor_id}")
def get_mentor_detail(mentor_id: int, db: Session = Depends(get_db)):
    # 1. 멘토 정보 가져오기
    mentor = db.query(Mentor).filter(Mentor.id == mentor_id).first()
    if not mentor:
        raise HTTPException(status_code=404, detail="존재하지 않는 멘토입니다.")

    mentor.views = (mentor.views or 0) + 1
    db.commit()
    db.refresh(mentor)
    user = db.query(User).filter(User.id == mentor.user_id).first()
    actual_profile_image = user.profile_image if user else None

    return {
        "id": mentor.id,
        "name": mentor.name or "멘토",
        "job_title": mentor.job_title or "직무 미정",
        "mentor_intro": mentor.mentor_intro or "<p>소개글이 없습니다.</p>",
        "career_history": mentor.career_history or [],
        "mentoring_topics": mentor.mentoring_topics or [],
        "detailed_experience": mentor.detailed_experience or [],
        "profile_image": actual_profile_image if (
            actual_profile_image and 
            actual_profile_image != "null" and 
            "unsplash" not in actual_profile_image
        ) else "https://upload.wikimedia.org/wikipedia/commons/7/7c/Profile_avatar_placeholder_large.png",
        "views": mentor.views,
    }


@router.get("/api/mentor/details/{user_id}")
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
        "price": mentor.price or "10,000 원",
    }


@router.post("/api/mentor/register/{user_id}")
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
    mentor.status = request.status           
    mentor.main_category = request.main_category 
    mentor.sub_category = request.sub_category   
    mentor.job_title = request.job_title
    mentor.career_history = request.career_history
    mentor.mentor_intro = request.mentor_intro
    mentor.mentoring_topics = request.mentoring_topics
    mentor.detailed_experience = request.detailed_experience

    db.commit()
    return {"message": "멘토 프로필 독립 등록 완료"}


"""
# 대시보드 API (주석 처리된 원본 유지)
@router.get("/api/mentor/dashboard/{user_id}")
def get_mentor_dashboard_data(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 사용자입니다.")

    mentor = db.query(Mentor).filter(Mentor.user_id == user_id).first()

    stats_data = {
        "name": user.name,
        "total_chats": getattr(user, "total_chats", 127),
        "total_earnings": getattr(user, "total_earnings", 9525),
        "average_rating": getattr(user, "average_rating", 4.9),
        "mentoring_hours": getattr(user, "mentoring_hours", 63.5),
    }

    upcoming_chats = []
    if mentor:
        today = date.today()
        bookings = db.query(Booking).filter(
            (Booking.mentor_id == mentor.id) | (Booking.mentor_id == mentor.user_id),
            Booking.booking_date >= today,
            Booking.status == "PAID"
        ).order_by(Booking.booking_date, Booking.booking_time).all()

        for b in bookings:
            mentee = db.query(User).filter(User.id == b.user_id).first()
            upcoming_chats.append({
                "id": b.id,
                "date": str(b.booking_date),
                "time": b.booking_time,
                "mentee_name": mentee.name if mentee else "예약자",
                "questions": b.questions
            })

    return {
        "stats": stats_data,
        "upcoming_chats": upcoming_chats,
    }
"""
@router.post("/api/upload/editor-image")
async def upload_editor_image(file: UploadFile = File(...)):
    """에디터 내부에 삽입되는 이미지를 imageupload 컨테이너에 저장합니다."""
    
    AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
    CONTAINER_NAME = "imageupload"  # 💡 새 컨테이너 이름 타겟팅!

    if not AZURE_CONNECTION_STRING:
        raise HTTPException(status_code=500, detail="Azure Storage 연결 정보가 없습니다.")

    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)

        # 1. 파일명 중복을 막기 위해 UUID 사용 + editor 폴더 경로 지정
        file_extension = file.filename.split(".")[-1]
        unique_filename = f"editor/{uuid.uuid4()}.{file_extension}"
        
        blob_client = container_client.get_blob_client(unique_filename)
        
        # 2. 파일 읽기
        file_contents = await file.read()
        
        # 3. Content-Type 설정 (브라우저에서 다운로드되지 않고 바로 보이게 하려면 필수!)
        content_settings = ContentSettings(content_type=file.content_type)
        
        # 4. Azure에 업로드
        blob_client.upload_blob(file_contents, overwrite=True, content_settings=content_settings)

        # 5. 저장된 이미지 URL 반환 (프론트엔드 ReactQuill로 전달됨)
        return {"url": blob_client.url}

    except Exception as e:
        print(f"🚨 에디터 이미지 업로드 실패: {e}")
        raise HTTPException(status_code=500, detail="이미지를 Azure에 업로드하는 중 오류가 발생했습니다.")

@router.get("/api/mentor/availability/{mentor_id}")
def get_mentor_availability(mentor_id: int, db: Session = Depends(get_db)):
    mentor = db.query(Mentor).filter(Mentor.id == mentor_id).first()
    if not mentor:
        return {} 

    today = date.today()
    
    # 과거 일정 자동 청소 (Lazy Cleanup)
    db.query(MentorAvailability).filter(
        MentorAvailability.mentor_id == mentor.id,
        MentorAvailability.date < today
    ).delete()
    db.commit()

    availability_rows = db.query(MentorAvailability).filter(
        MentorAvailability.mentor_id == mentor.id
    ).all()

    booking_rows = db.query(Booking).filter(
        Booking.mentor_id == mentor.id,
        Booking.status == "PAID"
    ).all()

    result: Dict[str, Dict[str, str]] = {}
    for row in availability_rows:
        dk = str(row.date)
        if dk not in result: result[dk] = {}
        result[dk][row.time] = "available"

    for row in booking_rows:
        dk = str(row.booking_date)
        if dk not in result: result[dk] = {}
        result[dk][row.booking_time] = "booked"

    return result


@router.post("/api/mentor/availability/bulk")
def save_mentor_availability(request: AvailabilityBulkRequest, db: Session = Depends(get_db)):
    mentor = db.query(Mentor).filter(Mentor.id == request.mentor_id).first()
    
    if not mentor:
        raise HTTPException(status_code=404, detail="멘토 정보가 없습니다.")

    real_mentor_id = mentor.id

    for date_str, times in request.schedules.items():
        db.query(MentorAvailability).filter(
            MentorAvailability.mentor_id == real_mentor_id,
            MentorAvailability.date == date_str,
        ).delete()

        for time_str in times:
            slot = MentorAvailability(mentor_id=real_mentor_id, date=date_str, time=time_str)
            db.add(slot)

    db.commit()
    return {"message": "가용 시간이 성공적으로 저장되었습니다."}


@router.post("/api/mentor/penalty")
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