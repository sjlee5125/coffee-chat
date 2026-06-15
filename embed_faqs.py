import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from openai import AzureOpenAI

load_dotenv()

# DB 연결
engine = create_engine("postgresql://postgres:soldesk0526@48.211.169.52:5432/postgres")

# Azure OpenAI 클라이언트
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("AZURE_API_VERSION", "2024-02-15-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

EMBEDDING_MODEL = "text-embedding-ada-002"

with engine.connect() as conn:
    # 임베딩 없는 FAQ 가져오기
    faqs = conn.execute(text(
        "SELECT id, question, answer, embedding_text FROM public.faqs WHERE embedding IS NULL"
    )).fetchall()

    print(f"임베딩할 FAQ: {len(faqs)}개")

    for faq in faqs:
        # 질문 + 답변 합쳐서 임베딩
        content = f"{faq.question} {faq.answer}"
        
        response = client.embeddings.create(
            input=content,
            model=EMBEDDING_MODEL
        )
        embedding = response.data[0].embedding

        conn.execute(text(
            "UPDATE public.faqs SET embedding = :embedding WHERE id = :id"
        ), {"embedding": str(embedding), "id": faq.id})
        
        print(f"✅ FAQ {faq.id} 임베딩 완료")

    conn.commit()
    print("🎉 모든 FAQ 임베딩 완료!")
