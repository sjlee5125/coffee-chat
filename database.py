from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import socket
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import auth # auth.py를 참조해야 합니다.
hostname = socket.gethostname()
if hostname == "coffeechat":
    # 클라우드 서버 내부에서는 옆방 DB로 바로 접속 (localhost)
    SQLALCHEMY_DATABASE_URL = "postgresql://postgres:soldesk0526@localhost:5432/postgres"
else:
    # 팀원들 노트북에서는 클라우드 서버 DB로 원격 접속 (외부 IP)
    SQLALCHEMY_DATABASE_URL = "postgresql://postgres:soldesk0526@48.211.169.52:5432/postgres"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    임시 구현: 토큰을 받아 유저 정보를 반환합니다.
    실제 운영 환경에서는 auth.py의 검증 로직을 그대로 가져와 사용하는 것이 좋습니다.
    """
    try:
        # auth.py에 있는 decode_token 함수를 사용한다고 가정합니다.
        payload = auth.decode_token(token)
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰입니다.")
        return {"user_id": user_id}
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증 실패")