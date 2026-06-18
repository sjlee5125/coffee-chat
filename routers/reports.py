from fastapi import APIRouter, Response, HTTPException, Depends
from sqlalchemy.orm import Session
from models import CoffeeChatReport, ChatSession, get_db
from weasyprint import HTML
from fastapi.responses import StreamingResponse
import io

router = APIRouter()

@router.get("/api/pdf/download/{chat_id}")
async def download_pdf(chat_id: int, db: Session = Depends(get_db)):
    # 1. 리포트 데이터 조회
    report = db.query(CoffeeChatReport).join(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    if not report or not report.ai_advice:
        raise HTTPException(status_code=404, detail="리포트 데이터가 없습니다.")

    # 2. PDF로 만들 HTML 템플릿 작성 (여기에 CSS를 입혀 레이아웃을 잡습니다)
    html_content = f"""
    <html>
        <head>
            <style>
                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 20px; }}
                h1 {{ color: #1e3a8a; text-align: center; }}
                .content {{ line-height: 1.6; color: #374151; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            </style>
        </head>
        <body>
            <h1>티타임 AI 분석 리포트</h1>
            <div class="content">
                {report.ai_advice.replace('\n', '<br>')}
            </div>
        </body>
    </html>
    """

    # 3. PDF 생성
    pdf_file = HTML(string=html_content).write_pdf()

    # 4. 파일로 즉시 전달
    return Response(
        content=pdf_file,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=teatime_report_{chat_id}.pdf"}
    )