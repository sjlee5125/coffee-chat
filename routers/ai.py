import os
from fastapi import APIRouter, HTTPException
from schemas import AIQuestionRequest
from openai import AzureOpenAI

router = APIRouter(
    prefix="/api/ai",
    tags=["AI"]
)

# Azure OpenAI 연동 설정
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION")

ai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=AZURE_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)

@router.post("/generate-questions")
async def generate_ai_questions(request: AIQuestionRequest):
    """Azure OpenAI를 사용한 커피챗 대화 추천 질문 자동 생성 API"""
    if not request.memo.strip():
        raise HTTPException(status_code=400, detail="메모 내용이 비어 있습니다.")

    try:
        system_prompt = (
            "당신은 커리어 멘토링 서비스의 질문 추천 AI 어시스턴트입니다. "
            "사용자가 멘토에게 질문하고 싶은 내용을 두서없이 작성한 '메모'를 주면, "
            "그 내용을 명확하고 전문적인 멘토링 질문 리스트(최대 3~4개)로 정제하여 답변해야 합니다. "
            "답변 서론이나 결론은 모두 제외하고, 질문 리스트만 번호 형태로 출력하세요."
        )
        user_prompt = f"사용자 메모:\n{request.memo}"

        response = ai_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=1000,
        )

        return {"aiQuestions": response.choices[0].message.content.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 질문 생성 중 내부 오류가 발생했습니다: {str(e)}")