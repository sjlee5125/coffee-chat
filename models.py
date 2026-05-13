from sqlalchemy import create_engine, Column, Integer, String, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import enum

# DB 연결 설정 (기존 테스트 정보를 바탕으로 구성)
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://team03_admin:team03_pw@localhost/coffeechat"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserRole(enum.Enum):
    MENTOR = "mentor"
    MENTEE = "mentee"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=True) # SNS 로그인 시 null 가능
    password = Column(String(255), nullable=True)             # SNS 로그인 시 null 가능
    nickname = Column(String(50))
    role = Column(Enum(UserRole), default=UserRole.MENTEE)
    major = Column(String(100)) # 멘토 리스트 필터링용
    
    # SNS 로그인 식별자
    kakao_id = Column(String(100), unique=True, nullable=True)
    provider = Column(String(20), nullable=True) # "kakao" 등

# DB 테이블 생성 함수
def create_tables():
    Base.metadata.create_all(bind=engine)

# DB 세션 의존성 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()