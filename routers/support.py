# routers/support.py
# FAQ 조회 + 1:1 문의 제출 + 관리자 API

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from models import FAQ, Inquiry, InquiryStatus

router = APIRouter(prefix="/api/support", tags=["support"])


# ══════════════════════════════════════════════════════
# Pydantic 스키마
# ══════════════════════════════════════════════════════

class FAQOut(BaseModel):
    id: int
    category: str
    question: str
    answer: str
    sort_order: int

    class Config:
        from_attributes = True


class InquiryCreate(BaseModel):
    category: str
    title: str
    body: str
    email: EmailStr
    user_id: Optional[int] = None   # 로그인 사용자면 전달


class InquiryOut(BaseModel):
    id: int
    category: str
    title: str
    body: str
    email: str
    status: str
    answer: Optional[str]
    answered_at: Optional[datetime]
    admin_note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class InquiryAnswerRequest(BaseModel):
    answer: str
    admin_note: Optional[str] = None
    status: Optional[str] = "answered"   # answered | closed | in_review


# ══════════════════════════════════════════════════════
# ─── FAQ 엔드포인트 ───────────────────────────────────
# ══════════════════════════════════════════════════════

@router.get("/faqs", response_model=list[FAQOut])
def get_faqs(
    category: Optional[str] = Query(None, description="카테고리 필터 (없으면 전체)"),
    q: Optional[str] = Query(None, description="검색 키워드"),
    db: Session = Depends(get_db),
):
    """활성 FAQ 목록 반환. 챗봇 RAG 및 프론트 FAQ 패널 공용."""
    query = db.query(FAQ).filter(FAQ.is_active == True)

    if category and category != "전체":
        query = query.filter(FAQ.category == category)

    if q:
        like = f"%{q}%"
        query = query.filter(
            (FAQ.question.ilike(like)) | (FAQ.answer.ilike(like))
        )

    return query.order_by(FAQ.category, FAQ.sort_order).all()


@router.get("/faqs/categories", response_model=list[str])
def get_faq_categories(db: Session = Depends(get_db)):
    """FAQ 카테고리 목록 반환"""
    rows = (
        db.query(FAQ.category)
        .filter(FAQ.is_active == True)
        .distinct()
        .order_by(FAQ.category)
        .all()
    )
    return ["전체"] + [r[0] for r in rows]


# ──────────────────────────────────────────────────────
# 관리자 전용: FAQ CRUD
# ──────────────────────────────────────────────────────

class FAQCreate(BaseModel):
    category: str
    question: str
    answer: str
    sort_order: int = 0

class FAQUpdate(BaseModel):
    category: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.post("/admin/faqs", response_model=FAQOut, status_code=201)
def create_faq(payload: FAQCreate, db: Session = Depends(get_db)):
    faq = FAQ(
        **payload.model_dump(),
        embedding_text=f"{payload.question} {payload.answer}",
    )
    db.add(faq)
    db.commit()
    db.refresh(faq)
    return faq


@router.patch("/admin/faqs/{faq_id}", response_model=FAQOut)
def update_faq(faq_id: int, payload: FAQUpdate, db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(404, "FAQ를 찾을 수 없습니다.")
    for field, val in payload.model_dump(exclude_none=True).items():
        setattr(faq, field, val)
    faq.embedding_text = f"{faq.question} {faq.answer}"
    db.commit()
    db.refresh(faq)
    return faq


@router.delete("/admin/faqs/{faq_id}", status_code=204)
def delete_faq(faq_id: int, db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(404, "FAQ를 찾을 수 없습니다.")
    faq.is_active = False   # 소프트 삭제
    db.commit()


# ══════════════════════════════════════════════════════
# ─── 1:1 문의 엔드포인트 ─────────────────────────────
# ══════════════════════════════════════════════════════

@router.post("/inquiries", response_model=InquiryOut, status_code=201)
def create_inquiry(payload: InquiryCreate, db: Session = Depends(get_db)):
    """1:1 문의 접수"""
    inquiry = Inquiry(
        user_id=payload.user_id,
        category=payload.category,
        title=payload.title,
        body=payload.body,
        email=payload.email,
        status=InquiryStatus.PENDING,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return inquiry


# ──────────────────────────────────────────────────────
# 관리자 전용: 문의 관리
# ──────────────────────────────────────────────────────

@router.get("/admin/inquiries", response_model=list[InquiryOut])
def list_inquiries(
    status: Optional[str] = Query(None, description="pending | in_review | answered | closed"),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """관리자: 문의 목록 (페이지네이션)"""
    query = db.query(Inquiry)

    if status:
        try:
            status_enum = InquiryStatus(status)
            query = query.filter(Inquiry.status == status_enum)
        except ValueError:
            raise HTTPException(400, f"유효하지 않은 status: {status}")

    if category:
        query = query.filter(Inquiry.category == category)

    total = query.count()
    items = (
        query.order_by(Inquiry.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return items


@router.get("/admin/inquiries/{inquiry_id}", response_model=InquiryOut)
def get_inquiry(inquiry_id: int, db: Session = Depends(get_db)):
    inquiry = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inquiry:
        raise HTTPException(404, "문의를 찾을 수 없습니다.")
    return inquiry


@router.patch("/admin/inquiries/{inquiry_id}/answer", response_model=InquiryOut)
def answer_inquiry(
    inquiry_id: int,
    payload: InquiryAnswerRequest,
    admin_user_id: int = Query(..., description="답변 관리자 user_id"),
    db: Session = Depends(get_db),
):
    """관리자: 문의 답변 등록 및 상태 변경"""
    inquiry = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inquiry:
        raise HTTPException(404, "문의를 찾을 수 없습니다.")

    inquiry.answer = payload.answer
    inquiry.answered_at = datetime.utcnow()
    inquiry.answered_by = admin_user_id

    if payload.admin_note:
        inquiry.admin_note = payload.admin_note

    try:
        inquiry.status = InquiryStatus(payload.status)
    except ValueError:
        raise HTTPException(400, f"유효하지 않은 status: {payload.status}")

    db.commit()
    db.refresh(inquiry)
    return inquiry


@router.get("/admin/inquiries/stats/summary")
def inquiry_stats(db: Session = Depends(get_db)):
    """관리자 대시보드용 문의 현황 요약"""
    from sqlalchemy import func as sqlfunc

    rows = (
        db.query(Inquiry.status, sqlfunc.count(Inquiry.id))
        .group_by(Inquiry.status)
        .all()
    )
    return {row[0].value: row[1] for row in rows}