from fastapi import FastAPI

app = FastAPI(
    title="CoffeeChat API",
    description="AI 기반 멘토링 플랫폼 백엔드 서버",
    version="1.0.0"
)

@app.get("/")
async def root():
    return {"message": "커피챗 API 서버가 정상적으로 실행 중입니다 ☕"}