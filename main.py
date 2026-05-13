from fastapi import FastAPI
import pymysql
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용 (테스트용)
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"status": "Server is Running", "project": "CoffeeChat"}

@app.get("/db-test")
def test_db():
    try:
        # 아까 Docker로 만든 MySQL 연결 테스트
        conn = pymysql.connect(
            host="localhost",
            user="team03_admin",
            password="team03_pw",
            db="coffeechat"
        )
        return {"status": "DB Connected Successfully"}
    except Exception as e:
        return {"error": str(e)}
    



