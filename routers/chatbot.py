import os
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import get_db
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(tags=["Chatbot"])

try:
    from openai import AzureOpenAI
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_KEY"),
        api_version=os.getenv("AZURE_API_VERSION", "2024-02-15-preview"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")
    print("✅ Chatbot Azure OpenAI 초기화 성공!")
except Exception as e:
    client = None
    print(f"⚠️ Chatbot Azure OpenAI 초기화 실패: {e}")


class ChatRequest(BaseModel):
    message: str
    history: Optional[list] = []


@router.post("/chatbot")
def chatbot(request: ChatRequest, db: Session = Depends(get_db)):
    print(f"[챗봇] 질문: {request.message}")

    if not client:
        return {"answer": "현재 AI 서비스가 준비 중입니다. 잠시 후 다시 시도해주세요."}

    try:
        # 1. 키워드 기반 FAQ 검색
        keywords = request.message.replace('?', '').replace('!', '').split()
        
        conditions = " OR ".join([
            f"(question ILIKE '%{kw}%' OR answer ILIKE '%{kw}%')"
            for kw in keywords if len(kw) > 1
        ])
        
        if conditions:
            result = db.execute(text(f"""
                SELECT question, answer
                FROM public.faqs
                WHERE is_active = true
                AND ({conditions})
                LIMIT 3
            """)).fetchall()
        else:
            result = []

        # 2. 컨텍스트 구성
        context = ""
        for row in result:
            context += f"Q: {row.question}\nA: {row.answer}\n\n"

        # 3. 프롬프트 구성
        system_prompt = """당신은 teatimes(티타임즈) 서비스의 친절한 고객 지원 챗봇입니다.
teatimes는 현직자 멘토와 멘티를 연결하는 커피챗 멘토링 플랫폼입니다.

아래 FAQ를 참고해서 사용자 질문에 답변해주세요.
FAQ에 없는 내용은 "고객센터에 문의해주세요"라고 안내해주세요.
답변은 친절하고 간결하게 2-3문장으로 해주세요.

[참고 FAQ]
""" + (context if context else "관련 FAQ가 없습니다. 고객센터로 안내해주세요.")

        # 4. 대화 히스토리 포함
        messages = [{"role": "system", "content": system_prompt}]
        for h in request.history[-6:]:
            messages.append(h)
        messages.append({"role": "user", "content": request.message})

        # 5. Azure OpenAI 호출
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=messages,
            temperature=0.3,
            max_tokens=300
        )

        answer = response.choices[0].message.content
        print(f"[챗봇] 답변: {answer}")
        return {"answer": answer}

    except Exception as e:
        print(f"[챗봇] 에러: {e}")
        return {"answer": "죄송합니다. 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}