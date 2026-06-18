import os
import re
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.orm import Session
from models import get_db, CoffeeChatReport, ChatSession, Booking
from weasyprint import HTML
from azure.storage.blob import BlobServiceClient
from database import SessionLocal
router = APIRouter()

AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
AZURE_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_CONNECTION_STRING", "").split("AccountName=")[1].split(";")[0] if "AccountName=" in os.getenv("AZURE_CONNECTION_STRING", "") else "coffeechat"
PDF_CONTAINER_NAME = "advicepdf"


def upload_pdf_to_azure(pdf_bytes: bytes, blob_name: str) -> str:
    blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
    container_client = blob_service_client.get_container_client(PDF_CONTAINER_NAME)
    try:
        container_client.create_container()
    except Exception:
        pass  # 이미 존재하면 무시
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(pdf_bytes, overwrite=True)
    url = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{PDF_CONTAINER_NAME}/{blob_name}"
    return url


def markdown_to_html(text: str) -> str:
    text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if '|' in line and i + 1 < len(lines) and re.match(r'^[\|\s\-:]+$', lines[i + 1]):
            result.append('<table>')
            headers = [h.strip() for h in line.strip('|').split('|')]
            result.append('<thead><tr>')
            for h in headers:
                result.append(f'<th>{h}</th>')
            result.append('</tr></thead><tbody>')
            i += 2
            while i < len(lines) and '|' in lines[i]:
                cells = [c.strip() for c in lines[i].strip('|').split('|')]
                result.append('<tr>')
                for c in cells:
                    result.append(f'<td>{c}</td>')
                result.append('</tr>')
                i += 1
            result.append('</tbody></table>')
        else:
            if line.strip():
                result.append(f'<p>{line}</p>')
            else:
                result.append('<br>')
            i += 1
    return '\n'.join(result)


def generate_pdf_bytes(summary: str, ai_advice: str, mentor_name: str) -> bytes:
    # 🌟 이모지 제거/대체 함수
    def clean_emojis(text):
        if not text: return ""
        # 주요 이모지들을 텍스트로 대체하거나 삭제 (필요시 추가)
        emoji_map = {
            "💬": "[대화]", "📌": "[중요]", "🔄": "[순환]", "💡": "[Tip]", 
            "🏃": "[액션]", "📋": "[목록]", "🔥": "[핵심]", "🍿": "[참고]", "🔭": "[전망]"
        }
        for emoji, text_sub in emoji_map.items():
            text = text.replace(emoji, text_sub)
        return text

    # 🌟 데이터 클리닝 적용
    summary = clean_emojis(summary)
    ai_advice = clean_emojis(ai_advice)

    summary_html = summary.replace('\n', '<br>') if summary else ''
    advice_html = markdown_to_html(ai_advice) if ai_advice else ''

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
        * {{ font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif; box-sizing: border-box; }}
        body {{ padding: 32px 40px; color: #1e293b; font-size: 13px; line-height: 1.8; }}
        .header {{ border-bottom: 2px solid #312e81; padding-bottom: 16px; margin-bottom: 28px; }}
        .header h1 {{ color: #312e81; font-size: 22px; font-weight: 900; margin: 0 0 4px 0; }}
        .header p {{ color: #64748b; font-size: 12px; margin: 0; }}
        .section-title {{ color: #312e81; font-size: 15px; font-weight: 700; margin: 28px 0 10px 0; padding-bottom: 6px; border-bottom: 1px solid #e2e8f0; }}
        .section-box {{ background: #f8fafc; border-radius: 8px; padding: 16px 20px; margin-bottom: 8px; white-space: pre-wrap; word-break: keep-all; }}
        h2 {{ color: #312e81; font-size: 14px; font-weight: 700; margin: 20px 0 6px 0; }}
        h3 {{ color: #3730a3; font-size: 13px; font-weight: 700; margin: 16px 0 4px 0; }}
        strong {{ font-weight: 700; }}
        table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12px; }}
        th {{ background: #e0e7ff; color: #312e81; font-weight: 700; padding: 8px 10px; border: 1px solid #c7d2fe; text-align: left; }}
        td {{ padding: 7px 10px; border: 1px solid #e2e8f0; vertical-align: top; word-break: keep-all; }}
        tr:nth-child(even) td {{ background: #f8fafc; }}
        p {{ margin: 4px 0; }}
      </style>
    </head>
    <body>
      <div class="header">
        <h1>티타임 AI 분석 리포트</h1>
        <p>{mentor_name} 님과의 대화 분석</p>
      </div>
      <div class="section-title">대화 요약</div>
      <div class="section-box">{summary_html}</div>
      <div class="section-title">페이스메이커 어드바이스</div>
      <div>{advice_html}</div>
    </body>
    </html>
    """
    return HTML(string=html_content).write_pdf()

def create_and_upload_report_pdf(chat_id: int): 
    print(f"🚀 [PDF 함수 진입] chat_id: {chat_id} 작업을 시작합니다.")
    db = SessionLocal()
    try:
        report = (
            db.query(CoffeeChatReport)
            .join(ChatSession, CoffeeChatReport.chatsession_id == ChatSession.id)
            .filter(ChatSession.booking_id == chat_id)
            .first()
        )
        print(f"✅ [PDF] DB 조회 완료")
        
        if not report or not report.ai_advice:
            print(f"[PDF] chat_id={chat_id} 리포트 없음, 스킵")
            return

        booking = db.query(Booking).filter(Booking.id == chat_id).first()
        mentor_name = getattr(booking, "mentor_name", "멘토")

        print(f"🎨 [PDF] HTML 렌더링 시작...")
        # 🌟 중복 호출 제거하고 여기에서 한 번만 호출합니다.
        pdf_bytes = generate_pdf_bytes(
            summary=report.summary or "",
            ai_advice=report.ai_advice,
            mentor_name=mentor_name,
        )
        print(f"🎨 [PDF] 렌더링 완료, 바이트 크기: {len(pdf_bytes)} bytes")

        print(f"☁️ [PDF] Azure 업로드 시작...")
        blob_name = f"report_{chat_id}.pdf"
        pdf_url = upload_pdf_to_azure(pdf_bytes, blob_name)
        
        report.pdf_url = pdf_url
        setattr(report, "pdf_url", pdf_url)
        db.commit()
        print(f"🎉 [PDF] 최종 성공! DB 저장 완료: {pdf_url}")

    except Exception as e:
        print(f"🚨 [PDF] 진짜 범인 발견: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
# ── 엔드포인트 ──

@router.get("/api/report/pdf-url/{chat_id}")
async def get_pdf_url(chat_id: int, db: Session = Depends(get_db)):
    report = db.query(CoffeeChatReport).join(ChatSession, CoffeeChatReport.chatsession_id == ChatSession.id).filter(ChatSession.booking_id == chat_id).first()
    
    if not report:
        return {"status": "waiting", "pdf_url": None}
    
    # 🌟 getattr을 사용해 pdf_url 속성이 있는지 안전하게 확인
    pdf_url = getattr(report, "pdf_url", None)
    
    if not pdf_url:
        return {"status": "processing", "pdf_url": None}
        
    return {"status": "completed", "pdf_url": pdf_url}
@router.post("/api/report/generate-pdf/{chat_id}")
async def generate_pdf_manually(chat_id: int, background_tasks: BackgroundTasks):
    """수동 PDF 재생성 (에러 테스트용)"""
    print(f"🛠️ [테스트] {chat_id}번 방의 PDF 강제 생성을 시작합니다...")
    # 캐시 상관없이 무조건 PDF 생성을 백그라운드로 던집니다!
    background_tasks.add_task(create_and_upload_report_pdf, chat_id)
    
    return {"message": "PDF 생성 지시 완료! 백엔드 터미널 창을 확인하세요."}