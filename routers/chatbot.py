
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
    DEPLOYMENT_NAME = "gpt-4o-mini"
    EMBEDDING_MODEL = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
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
        # ✅ pgvector 대신 키워드 LIKE 검색으로 대체
        result = db.execute(text("""
            SELECT question, answer
            FROM public.faqs
            WHERE is_active = true
              AND (question ILIKE :keyword OR answer ILIKE :keyword OR embedding_text ILIKE :keyword)
            LIMIT 3
        """), {"keyword": f"%{request.message}%"}).fetchall()

        context = ""
        for row in result:
            context += f"Q: {row.question}\nA: {row.answer}\n\n"

        print(f"[챗봇] 유사 FAQ {len(result)}개 검색됨")

        system_prompt = """당신은 teatimes(티타임즈) 서비스의 친절한 고객 지원 챗봇입니다.
teatimes는 현직자 멘토와 멘티를 연결하는 커피챗 멘토링 플랫폼입니다.

아래 FAQ를 참고해서 사용자 질문에 답변해주세요.
FAQ에 없는 내용은 "고객센터에 문의해주세요"라고 안내해주세요.
답변은 친절하고 간결하게 2-3문장으로 해주세요.

[참고 FAQ]
""" + (context if context else "관련 FAQ가 없습니다. 고객센터로 안내해주세요.")

        messages = [{"role": "system", "content": system_prompt}]
        for h in request.history[-6:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": request.message})

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

        # import os
        # from typing import Optional
        # from fastapi import APIRouter, Depends
        # from pydantic import BaseModel
        # from sqlalchemy.orm import Session
        # from sqlalchemy import text
        # from models import get_db, FAQ
        # from dotenv import load_dotenv

        # load_dotenv()
        # router = APIRouter(tags=["Chatbot"])

        # try:
        #     from openai import AzureOpenAI
        #     client = AzureOpenAI(
        #         api_key=os.getenv("AZURE_OPENAI_KEY"),
        #         api_version=os.getenv("AZURE_API_VERSION", "2024-02-15-preview"),
        #         azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
        #     )
        #     DEPLOYMENT_NAME = "gpt-4o-mini"
        #     EMBEDDING_MODEL = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
        #     print("✅ Chatbot Azure OpenAI 초기화 성공!")
        # except Exception as e:
        #     client = None
        #     print(f"⚠️ Chatbot Azure OpenAI 초기화 실패: {e}")


        # class ChatRequest(BaseModel):
        #     message: str
        #     history: Optional[list] = []


        # # ✅ FAQ 임베딩 일괄 생성 엔드포인트 (최초 1회 or FAQ 추가 시 호출)
        # @router.post("/chatbot/embed-faqs")
        # def embed_faqs(db: Session = Depends(get_db)):
        #     """embedding이 없는 FAQ에 벡터 임베딩을 생성해서 저장"""
        #     if not client:
        #         return {"error": "AI 클라이언트 미초기화"}

        #     faqs = db.query(FAQ).filter(
        #         FAQ.is_active == True,
        #         FAQ.embedding == None   # embedding 없는 것만
        #     ).all()

        #     if not faqs:
        #         return {"message": "임베딩할 FAQ가 없습니다.", "count": 0}

        #     count = 0
        #     for faq in faqs:
        #         try:
        #             text_to_embed = f"{faq.question} {faq.answer}"
        #             resp = client.embeddings.create(
        #                 input=text_to_embed,
        #                 model=EMBEDDING_MODEL
        #             )
        #             faq.embedding = resp.data[0].embedding  # list[float] 그대로 저장
        #             count += 1
        #         except Exception as e:
        #             print(f"[임베딩 실패] FAQ id={faq.id}: {e}")

        #     db.commit()
        #     print(f"[임베딩] {count}개 완료")
        #     return {"message": f"{count}개 FAQ 임베딩 완료"}


        # @router.post("/chatbot")
        # def chatbot(request: ChatRequest, db: Session = Depends(get_db)):
        #     print(f"[챗봇] 질문: {request.message}")

        #     if not client:
        #         return {"answer": "현재 AI 서비스가 준비 중입니다. 잠시 후 다시 시도해주세요."}

        #     try:
        #         # 1. 질문 임베딩 생성
        #         embedding_response = client.embeddings.create(
        #             input=request.message,
        #             model=EMBEDDING_MODEL
        #         )
        #         query_embedding = embedding_response.data[0].embedding
        #         # ✅ list[float] → pgvector용 문자열 변환
        #         embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

        #         # 2. pgvector 코사인 유사도 검색
        #         result = db.execute(text("""
        #             SELECT question, answer,
        #                 1 - (embedding <=> CAST(:emb AS vector)) AS similarity
        #             FROM public.faqs
        #             WHERE embedding IS NOT NULL
        #             AND is_active = true
        #             ORDER BY embedding <=> CAST(:emb AS vector)
        #             LIMIT 3
        #         """), {"emb": embedding_str}).fetchall()

        #         # 3. 유사도 0.5 이상만 컨텍스트로 사용
        #         context = ""
        #         for row in result:
        #             if row.similarity > 0.5:
        #                 context += f"Q: {row.question}\nA: {row.answer}\n\n"

        #         print(f"[챗봇] 유사 FAQ {len(result)}개 / 사용된 컨텍스트: {len(context)}자")

        #         system_prompt = """당신은 teatimes(티타임즈) 서비스의 친절한 고객 지원 챗봇입니다.
        #         teatimes는 현직자 멘토와 멘티를 연결하는 커피챗 멘토링 플랫폼입니다.

        #         아래 FAQ를 참고해서 사용자 질문에 답변해주세요.
        #         FAQ에 없는 내용은 "고객센터에 문의해주세요"라고 안내해주세요.
        #         답변은 친절하고 간결하게 2-3문장으로 해주세요.

        #         [참고 FAQ]
        #         """ + (context if context else "관련 FAQ가 없습니다. 고객센터로 안내해주세요.")

        #         # 4. 대화 히스토리 구성 (assistant 첫 메시지 제외, user/assistant만)
        #         messages = [{"role": "system", "content": system_prompt}]
        #         for h in request.history[-6:]:
        #             role = h.get("role") if isinstance(h, dict) else getattr(h, "role", None)
        #             content = h.get("content") if isinstance(h, dict) else getattr(h, "content", None)
        #             if role in ("user", "assistant") and content:
        #                 messages.append({"role": role, "content": content})
        #         messages.append({"role": "user", "content": request.message})

        #         # 5. GPT-4o-mini 호출
        #         response = client.chat.completions.create(
        #             model=DEPLOYMENT_NAME,
        #             messages=messages,
        #             temperature=0.3,
        #             max_tokens=300
        #         )

        #         answer = response.choices[0].message.content
        #         print(f"[챗봇] 답변: {answer}")
        #         return {"answer": answer}

        #     except Exception as e:
        #         print(f"[챗봇] 에러: {e}")
        #         return {"answer": "죄송합니다. 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}    
