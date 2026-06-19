import os
import requests
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from pydantic import BaseModel
from schemas import UserRegisterRequest, UserLoginRequest 
# 💡 jwt 라이브러리는 jose 하나만 통일해서 사용합니다. (ExpiredSignatureError 추가)
from jose import jwt, JWTError, ExpiredSignatureError
from models import User, get_db, UserRole

router = APIRouter()

# ==========================================
# 1. 보안 설정
# ==========================================
SECRET_KEY = "coffee-chat-secret-key" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
KAKAO_CLIENT_ID = "e2eb2fe1d550c2b3da05dcad347a4517"
KAKAO_REDIRECT_URI = "http://48.211.169.52:8000/login/kakao/callback"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

# ==========================================
# 2. Pydantic 모델
# ==========================================
class EmailCheckRequest(BaseModel):
    email: str


class UserLoginRequest(BaseModel):
    email: str
    password: str


# ==========================================
# 3. 인증 유틸리티 함수
# ==========================================
def get_password_hash(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# 💡 [핵심] 완벽하게 예외 처리된 get_current_user 함수
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    # 프론트엔드에서 'null' 문자열을 보냈거나 토큰이 아예 없는 경우 방어
    if not token or token == "null":
        raise HTTPException(status_code=401, detail="토큰이 없습니다. 다시 로그인해 주세요.")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 정보가 유효하지 않습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # 1. 토큰 해석 시도
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
            
    # 💡 2. 각종 토큰 에러를 여기서 완벽하게 잡아내서 500 에러(가짜 CORS)를 방지합니다.
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="로그인이 만료되었습니다. 다시 로그인해 주세요.")
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"인증 오류 발생: {str(e)}")
        
    # 3. DB에서 유저 정보 조회
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
        
    return user


# ==========================================
# 4. API 엔드포인트
# ==========================================
@router.post("/check-email")
def check_email(req: EmailCheckRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if user:
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다.")
    return {"message": "사용 가능한 이메일입니다."}

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(request: UserRegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다.")
    
    user_role = UserRole.MENTOR if request.role.lower() == "mentor" else UserRole.MENTEE
    new_user = User(
        email=request.email,
        password_hash=get_password_hash(request.password),
        role=user_role,
        name=request.name,
        bio=request.bio,
        mbti=request.mbti,
        hashtags=request.hashtags,
        experience=request.experience,
        portfolio_url=request.portfolio_url,
        help_provide=request.help_provide,
        help_receive=request.help_receive,
        profile_image=request.profile_image,
        phone_number=request.phone_number,
        portfolio_file_path=request.portfolio_file_path
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    token = create_access_token(data={"sub": new_user.email, "user_id": new_user.id})
    return {"message": "회원가입 완료", "user_id": new_user.id, "access_token": token}

@router.post("/login")
def login(request: UserLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다.")
    
    token = create_access_token(data={"sub": user.email, "user_id": user.id})
    return {"access_token": token, "user_id": user.id, "user_name": user.name}


# ==========================================
# 5. 카카오 로직
# ==========================================
def get_kakao_token(code: str):
    url = "https://kauth.kakao.com/oauth/token"
    data = {"grant_type": "authorization_code", "client_id": KAKAO_CLIENT_ID, "redirect_uri": KAKAO_REDIRECT_URI, "code": code}
    response = requests.post(url, data=data)
    if response.status_code != 200: raise HTTPException(status_code=400, detail="카카오 토큰 실패")
    return response.json().get("access_token")

def get_kakao_user_info(access_token: str):
    url = "https://kapi.kakao.com/v2/user/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200: raise HTTPException(status_code=400, detail="카카오 유저 정보 실패")
    return response.json()