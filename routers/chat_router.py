from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

# models.py에서 정의한 테이블 객체와 DB 제너레이터 함수를 가져옵니다.
from models import CoffeeChatReport, get_db
# 기존에 사용하시던 AI 서비스 함수를 그대로 유지합니다.
from .ai_service import generate_wrapup_report 

router = APIRouter()

