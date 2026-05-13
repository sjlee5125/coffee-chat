import os
from dotenv import load_dotenv
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import HTTPException, status
import requests

# .env 로드
load_dotenv()

# 보안 및 카카오 설정 (환경 변수에서 호출)
SECRET_KEY = "coffee-chat-secret-key" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

KAKAO_CLIENT_ID = os.getenv("KAKAO_REST_API_KEY")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- 일반 로그인 보안 로직 ---
def get_password_hash(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- 카카오 REST API 로직 ---
def get_kakao_token(code: str):
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": KAKAO_CLIENT_ID,
        "redirect_uri": KAKAO_REDIRECT_URI,
        "code": code,
    }
    response = requests.post(url, data=data)
    if response.status_code != 200:
        # 에러 발생 시 카카오가 보내준 상세 메시지를 확인하면 디버깅이 빠릅니다.
        error_detail = response.json().get("error_description", "카카오 토큰 발급 실패")
        raise HTTPException(status_code=400, detail=error_detail)
    return response.json().get("access_token")

def get_kakao_user_info(access_token: str):
    url = "https://kapi.kakao.com/v2/user/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="카카오 사용자 정보 조회 실패")
    return response.json()