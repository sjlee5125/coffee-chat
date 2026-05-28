import os
from fastapi import APIRouter, HTTPException
from schemas import AIQuestionRequest
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(
    prefix="/api/ai",
    tags=["AI"]
)

# 💡 환경변수 안전하게 로드
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION")

# 💡 키가 누락되었을 때 서버가 바로 죽지 않도록 방어 로직 추가
if not all([AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, AZURE_DEPLOYMENT_NAME, AZURE_API_VERSION]):
    print("⚠️ [경고] Azure OpenAI 환경 변수가 일부 누락되었습니다. AI 기능이 작동하지 않습니다.")
    ai_client = None
else:
    ai_client = AzureOpenAI(
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
    )

@router.post("/generate-questions")
async def generate_ai_questions(request: AIQuestionRequest):
    # 💡 클라이언트가 제대로 생성되지 않았다면 에러 반환
    if ai_client is None:
        raise HTTPException(status_code=503, detail="AI 서비스가 현재 준비되지 않았습니다.")

    if not request.memo.strip():
        raise HTTPException(status_code=400, detail="메모 내용이 비어 있습니다.")

    try:
        system_prompt = (
            "당신은 커리어 멘토링 서비스의 질문 추천 AI 어시스턴트입니다. "
            "사용자가 멘토에게 질문하고 싶은 내용을 두서없이 작성한 '메모'를 주면, "
            "그 내용을 명확하고 전문적인 멘토링 질문 리스트(최대 3~4개)로 정제하여 답변해야 합니다. "
            "답변 서론이나 결론은 모두 제외하고, 질문 리스트만 번호(1., 2., 3.) 형태로 출력하세요."
        )
        
        response = ai_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME, # 💡 여기서 정확한 배포명을 사용합니다
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"사용자 메모:\n{request.memo}"},
            ],
            temperature=0.7,
            max_tokens=1000,
        )

        return {"aiQuestions": response.choices[0].message.content.strip()}
    
    except Exception as e:
        print(f" [AI 생성 에러]: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI 질문 생성 중 오류: {str(e)}")