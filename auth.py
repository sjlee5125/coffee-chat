import os
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import HTTPException, status
import requests

# 1. 보안 설정
SECRET_KEY = "coffee-chat-secret-key" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# 2. 카카오 설정 (직접 할당)
# 환경 변수 로드 문제 해결을 위해 실제 키와 URI를 변수에 직접 저장합니다.
KAKAO_CLIENT_ID = "e2eb2fe1d550c2b3da05dcad347a4517"
KAKAO_REDIRECT_URI = "http://48.211.169.52:5173/login/kakao/callback"
print(f"--- 서버 시작: CLIENT_ID={KAKAO_CLIENT_ID} ---")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- 일반 로그인 보안 로직 ---
def get_password_hash(password: str):
    """비밀번호 해싱"""
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    """비밀번호 검증"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    """서비스 전용 JWT 액세스 토큰 생성"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- 카카오 REST API 로직 ---
def get_kakao_token(code: str):
    """카카오 인가 코드로 액세스 토큰 요청"""
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": KAKAO_CLIENT_ID,
        "redirect_uri": KAKAO_REDIRECT_URI,
        "code": code,
    }
    
    response = requests.post(url, data=data)
    
    if response.status_code != 200:
        # 실패 시 카카오 서버의 상세 에러 메시지를 반환하여 디버깅을 돕습니다.
        error_data = response.json()
        error_msg = error_data.get("error_description", "카카오 토큰 발급 실패")
        raise HTTPException(status_code=400, detail=f"Kakao API Error: {error_msg}")
        
    return response.json().get("access_token")

def get_kakao_user_info(access_token: str):
    """액세스 토큰으로 카카오 사용자 정보 조회"""
    url = "https://kapi.kakao.com/v2/user/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="카카오 사용자 정보 조회 실패")
        
    return response.json()