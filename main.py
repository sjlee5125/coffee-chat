from fastapi import FastAPI, Depends, HTTPException, status # status 추가
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import quote
from models import User, get_db, create_tables, UserRole
import auth

create_tables()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/login/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    try:
        kakao_token = auth.get_kakao_token(code)
        kakao_user = auth.get_kakao_user_info(kakao_token)
        
        kakao_id = str(kakao_user.get("id"))
        
        # [수정] 닉네임을 가져오는 경로를 더 확실하게 변경 (User로 나오는 문제 해결)
        nickname = (
            kakao_user.get("properties", {}).get("nickname") or 
            kakao_user.get("kakao_account", {}).get("profile", {}).get("nickname") or 
            "사용자"
        )

        user = db.query(User).filter(User.kakao_id == kakao_id).first()
        if not user:
            user = User(
                kakao_id=kakao_id, 
                nickname=nickname, 
                role=UserRole.MENTEE, 
                provider="kakao"
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            # [추가] 기존 유저의 경우 최신 닉네임으로 업데이트 (선택 사항)
            if user.nickname != nickname:
                user.nickname = nickname
                db.commit()

        access_token = auth.create_access_token(data={"sub": user.kakao_id})

        # [수정] 한글 인코딩 및 리다이렉트 표준 상태 코드(302) 적용
        safe_nickname = quote(user.nickname)
        frontend_url = f"http://48.211.169.52:5173/?token={access_token}&nickname={safe_nickname}"
        
        print(f"🚀 [DEBUG] 최종 리다이렉트 주소: {frontend_url}")
        
        # status_code=302를 명시하여 브라우저 차단 가능성을 낮춥니다.
        return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)

    except Exception as e:
        print(f"❌ [ERROR] {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))