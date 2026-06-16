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

EMBEDDING_MODEL = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")

with engine.connect() as conn:
    faqs = conn.execute(text(
        "SELECT id, question, answer FROM public.faqs WHERE embedding IS NULL"
    )).fetchall()

    print(f"임베딩할 FAQ: {len(faqs)}개")
    print(f"사용 모델: {EMBEDDING_MODEL}")

    for faq in faqs:
        content = f"{faq.question} {faq.answer}"
        
        response = client.embeddings.create(
            input=content,
            model=EMBEDDING_MODEL
        )
        embedding = response.data[0].embedding
        
        # pgvector 형식으로 변환
        embedding_str = '[' + ','.join(map(str, embedding)) + ']'

        # SQLAlchemy text()에서 :: 캐스팅 문제 해결
        conn.execute(text(
            "UPDATE public.faqs SET embedding = cast(:embedding as vector) WHERE id = :id"
        ), {"embedding": embedding_str, "id": faq.id})
        
        print(f"✅ FAQ {faq.id} 임베딩 완료")

    conn.commit()
    print("🎉 모든 FAQ 임베딩 완료!")