import os
import json
import re
import time
import logging
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import TextAnalyticsClient
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from models import get_db

# import 다음에 바로 로드
load_dotenv()
logging.getLogger('fontTools.subset').setLevel(logging.ERROR)

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ImportError:
    print("🚨 fpdf2 없음. pip install fpdf2 실행해주세요.")

# ==========================================
# 🔑 1. API 키 및 엔드포인트 세팅
# ==========================================
LANGUAGE_ENDPOINT = os.environ.get("LANGUAGE_ENDPOINT")
LANGUAGE_KEY = os.environ.get("LANGUAGE_KEY")

# 💡 [방어 로직] 키가 정상적인 문자열(String)일 때만 Azure 클라이언트를 연결합니다.
text_analytics_client = None
if LANGUAGE_KEY and LANGUAGE_ENDPOINT:
    text_analytics_client = TextAnalyticsClient(
        endpoint=LANGUAGE_ENDPOINT, 
        credential=AzureKeyCredential(LANGUAGE_KEY)
    )

# 💡 [핵심 수정] 파이프라인도 Azure OpenAI 키를 바라보도록 변경합니다!
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4o-2")
AZURE_API_VERSION = os.environ.get("AZURE_API_VERSION", "2024-12-01-preview")

MASKING_DEPLOYMENT = "gpt-4o-mini" 
SUMMARY_DEPLOYMENT = "gpt-4o"              

# 💡 OpenAI 클라이언트도 키가 있을 때만 연결하도록 방어할 수 있습니다.
openai_client = None
if AZURE_OPENAI_KEY:
    openai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=AZURE_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# ==========================================
# ⚡ Agent 0: Regex Masking
# ==========================================
def agent_regex_masking(text):
    print("⚡ [Agent 0] Regex 가동...")
    text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[기밀_이메일]', text)
    text = re.sub(r'01[0-9][\-\s]?\d{3,4}[\-\s]?\d{4}', '[기밀_연락처]', text)
    text = re.sub(r'\d{6}[\-\s]?[1-4]\d{6}', '[기밀_주민번호]', text)
    text = re.sub(r'[\d,]+(?:\s*만|\s*억|\s*천)?\s*원', '[기밀_금액]', text)
    text = re.sub(r'[\d\.]+\s*%', '[기밀_비율]', text)
    text = re.sub(r'프로젝트\s+[가-힣A-Za-z0-9]+', '[기밀_프로젝트]', text)
    text = re.sub(r'[가-힣A-Za-z0-9]+\s*프로젝트', '[기밀_프로젝트]', text)
    text = re.sub(r'(DAU|MAU|가입자|트래픽|방문자)(?:\s*수)?\s*[\d,\.]+(?:만|천)?\s*(?:명|건|회)?', r'\1 [기밀_지표]', text)
    text = re.sub(r'(시리즈|Series)\s*[A-Z]|(시드|Pre-A)\s*(?:투자|라운드)?', '[기밀_투자라운드]', text)
    text = re.sub(r'([가-힣a-zA-Z0-9]+\s*(?:팀|본부|실|파트))\s*[\d,\.]+(?:여)?\s*명', r'\1 [기밀_조직규모]', text)
    text = re.sub(r'(?:고과|인사평가|평가)?\s*[SABCD][\+\-]?\s*등급', '[기밀_인사평가]', text)
    text = re.sub(r'([가-힣A-Za-z0-9]+(?:사|기업|업체|전자|차|은행)?)(?:와|이랑|에|과)\s*(?:계약|MOU|납품|제휴|파트너십)', '[기밀_고객사]와 계약/제휴', text)
    text = re.sub(r'(?:내년|올해|상반기|하반기)?\s*(?:[1-4]분기|Q[1-4])\s*(?:출시|런칭|오픈|진출|배포)', '[기밀_일정] 런칭', text)
    text = re.sub(r'(?:코스피|코스닥|나스닥)?\s*(?:상장|IPO|인수|합병|M&A)\s*(?:준비|예정|진행|추진|실사)', '[기밀_M&A/IPO] 진행', text)
    text = re.sub(r'([A-Za-z0-9가-힣]+)(?:로|으로)\s*(?:마이그레이션|전환|이관)|(?:랜섬웨어|디도스|해킹)\s*(?:감염|공격|터져서)', '[기밀_보안/인프라]', text)
    return text

# ==========================================
# 🛡️ Agent 1: Azure PII
# ==========================================
def agent_azure_pii(text):
# 💡 [추가] 클라이언트가 None이면 바로 통과시키도록 방어 로직 추가
    if text_analytics_client is None:
        print("⚠️ [경고] Azure API 키가 없어서 Agent 1(PII)을 건너뛰고 Agent 2로 넘어갑니다.")
        return text
    
    print("🛡️ [Agent 1] Azure PII 가동...")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = text_analytics_client.recognize_pii_entities([text], language="ko")
            if not response[0].is_error:
                return response[0].redacted_text
            else:
                print(f"⚠️ Azure 내부 에러: {response[0].error.message}")
        except Exception as e:
            error_msg = str(e)
            print(f"🚨 Azure PII 에러 (시도 {attempt + 1}/{max_retries})")
            if "429" in error_msg or "Too Many Requests" in error_msg:
                time.sleep(3)
            else:
                time.sleep(2)
    print("❌ Azure PII 실패.")
    return text

# ==========================================
# 🕵️ Agent 2: LLM JSON Masking
# ==========================================
def agent_llm_masking(text):
    print("🕵️ [Agent 2] Masking AI 가동...")
    system_prompt = """
    당신은 IT 기업의 최고 보안 책임자(CISO)입니다.
    제공된 텍스트에서 잔여 기밀 정보를 찾아내세요.
    [잔여 마스킹 대상]
    1. 학교, 대학교 등 학력 정보
    2. 직장명, 소속 고유명사
    3. 구체적인 보상 및 처우
    4. 미공개 특허 및 핵심 기술
    5. 인증/크레덴셜
    6. 사람 이름
    7. 음차/변형된 개인정보
    반드시 아래 JSON 형식으로만 출력하세요.
    {"replacements": [{"original": "한국대학교", "masked": "[기밀_학교]"}]}
    """
    try:
        response = openai_client.chat.completions.create(
            model=MASKING_DEPLOYMENT,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=10000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"출력은 반드시 'replacements' 키를 가진 JSON으로 주세요.\n\n{text}"}
            ]
        )
        result_json = json.loads(response.choices[0].message.content)
        replacements = result_json.get("replacements", [])
        masked_text = text
        for item in replacements:
            original = item.get("original", "")
            masked = item.get("masked", "")
            if original:
                masked_text = masked_text.replace(original, masked)
        return masked_text
    except Exception as e:
        print("🚨 Masking AI 에러:", e)
        return text

# ==========================================
# 📝 Agent 3: LLM Summary
# ==========================================
def agent_llm_summary(safe_text):
    print("📝 [Agent 3] Summary AI 가동...")
    system_prompt = """
    당신은 커피챗 매칭 플랫폼의 수석 데이터 아키텍트입니다.
    커피챗 대화 스크립트에서 객관적 사실만을 발라내어 아래 JSON 구조로 변환하세요.
    {
        "session_metadata": {
            "industry_and_role": "주요 산업군 및 직무",
            "guest_as_is": "게스트의 현재 상황과 병목",
            "guest_to_be": "게스트의 목표"
        },
        "core_agendas": [
            {
                "agenda_title": "핵심 논의 안건",
                "guest_context": "게스트 질문/한계점",
                "host_solution": "호스트 해결책"
            }
        ],
        "extracted_keywords": {
            "tools_and_skills": ["하드스킬 키워드"],
            "business_terms": ["비즈니스 용어"]
        },
        "session_consensus": "최종 합의점"
    }
    """
    try:
        response = openai_client.chat.completions.create(
            model=SUMMARY_DEPLOYMENT,
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=4000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": safe_text}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

# ==========================================
# 📊 PDF 생성
# ==========================================
def generate_pdf_report(parsed_json, output_filename):
    pdf = FPDF()
    pdf.add_page()
    font_path = "C:/Windows/Fonts/malgun.ttf"
    if os.path.exists(font_path):
        pdf.add_font("Malgun", "", font_path)
        bold_font = "C:/Windows/Fonts/malgunbd.ttf"
        pdf.add_font("Malgun", "B", bold_font if os.path.exists(bold_font) else font_path)
        pdf.set_font("Malgun", size=12)
    else:
        pdf.set_font("Arial", size=12)

    def safe_print_text(text, max_chars_per_line=45):
        if not text:
            text = "내용 없음"
        text_str = str(text)
        paragraphs = text_str.split('\n')
        for para in paragraphs:
            if not para.strip():
                pdf.ln(8)
                continue
            while len(para) > max_chars_per_line:
                chunk = para[:max_chars_per_line]
                pdf.cell(0, 8, chunk, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                para = para[max_chars_per_line:]
            if para:
                pdf.cell(0, 8, para, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Malgun", "B", 18)
    pdf.cell(0, 15, "커피챗 상세 요약 리포트", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(5)

    def write_section(title, content, is_list=False):
        pdf.set_font("Malgun", "B", 14)
        pdf.cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Malgun", "", 11)
        if is_list and content:
            for i, item in enumerate(content, 1):
                safe_print_text(f"{i}. {item}")
        else:
            safe_print_text(content)
        pdf.ln(5)

    meta = parsed_json.get("session_metadata", {})
    bg_content = f"[현재 상황]\n{meta.get('guest_as_is', '')}\n\n[목표]\n{meta.get('guest_to_be', '')}"
    write_section("1. 게스트 상황 및 목표", bg_content)

    pdf.set_font("Malgun", "B", 14)
    pdf.cell(0, 10, "2. 핵심 논의 안건", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for i, disc in enumerate(parsed_json.get("core_agendas", []), 1):
        pdf.set_font("Malgun", "B", 12)
        safe_print_text(f"주제 {i}: {disc.get('agenda_title', '')}")
        pdf.set_font("Malgun", "", 11)
        safe_print_text(f"- 게스트 상황/질문: {disc.get('guest_context', '')}")
        safe_print_text(f"- 호스트 해결책: {disc.get('host_solution', '')}")
        pdf.ln(3)

    write_section("3. 최종 합의점 및 결론", parsed_json.get("session_consensus", ""))
    pdf.output(output_filename)

# ==========================================
# 🚀 라우터 (함수 정의 이후에 선언!)
# ==========================================
from models import get_db, ChatSession
import os
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()

# 💡 PDF용 데이터를 안전하게 보관할 임시 폴더를 만듭니다.
os.makedirs("summary_data", exist_ok=True)

@router.post("/api/chat-session/{chat_id}/generate-summary")
async def generate_summary(chat_id: int, request: Request, db: Session = Depends(get_db)):
    print(f"🚀 [{chat_id}번 방] 파이프라인 가동!")

    session = db.query(ChatSession).filter(ChatSession.booking_id == chat_id).first()
    
    # STT 대화가 있으면 쓰고, 없으면 완벽한 바이오 면접 대본 사용!
    if session and session.stt_text:
        raw_text = session.stt_text
    else:
        raw_text = """
    Host: 아, 아. 네, 아름 님 안녕하세요. 목소리 잘 들리시나요?
    Guest: 아, 네! 성현 님 안녕하세요. 아주 잘 들립니다! 퇴근하시고 피곤하실 텐데 이렇게 시간 내주셔서 정말 감사드려요.
    Host: 아닙니다. 저도 대학원 석사 졸업하고 취업 준비할 때 연구소 문턱이 너무 높게 느껴져서 고생했던 기억이 나네요. (웃음) 사전 질문지 보니까 연세대학교 생명공학과에서 석사 졸업하시고 지금 넥스트바이오 연구소 쪽에 지원하려고 준비 중이시라고요. 반갑습니다.
    Guest: 네, 맞습니다. 지난 2월에 석사 학위 받고 지금 한 석 달째 본격적으로 구직 활동을 하고 있는데요. 서류는 몇 번 통과해서 면접을 보긴 했는데, 대학원 실습실에서 했던 실험이랑 기업 연구소에서 요구하는 실무 역량 사이에 간극이 좀 큰 것 같아서 매번 면접에서 고배를 마셨습니다. 그래서 현직자이신 성현 님께 조언을 구하고자 신청하게 되었습니다.
    Host: 아... 면접까지 가셨는데 떨어지셨다니 마음이 많이 쓰이셨겠어요. 그래도 석사 학위가 있으시고 서류 통과가 된다는 건 기본적인 스펙이나 연구 역량은 검증되셨다는 뜻이에요. 보통 면접에서 어떤 질문을 받았을 때 가장 답변하기 어려우셨나요?
    Guest: 어... 가장 뼈아팠던 질문이 "본인이 석사 논문에서 진행한 세포 배양 실험은 학술적인 의미는 있지만, 우리 회사의 현재 신약 파이프라인 대량 생산 공정에는 어떻게 적용할 수 있겠냐"라는 질문이었어요. 저는 그냥 랩실 수준에서 웰 플레이트에 키우는 실험만 해봤다 보니, 공장 규모의 대량 생산이나 스케일업(Scale-up) 관점에서는 답변을 아예 못 하겠더라고요.
    Host: 아, 그 질문은 제약·바이오 면접관들이 단골로 던지는 압박 질문이에요. (웃음) 기업은 결국 이윤을 내는 곳이기 때문에, 연구소에서도 랩 스케일의 실험이 상업 생산으로 이어질 수 있는가를 항상 고민하거든요. 아름 님이 석사 과정 중에 주로 다루셨던 분석 장비나 실험 테크닉은 어떤 게 있나요?
    Guest: 저는 주로 단백질 정제랑 분석을 메인으로 해서, HPLC(고성능 액체 크로마토그래피) 장비를 가장 많이 다루었고요. 웨스턴 블롯(Western Blot)이나 ELISA 분석, 그리고 기본적인 동물 세포 배양 기술을 가지고 있습니다. 논문도 면역 항암제 관련 단백질 발현에 대한 주제로 썼고요.
    Host: 오, HPLC를 메인으로 다루실 줄 안다는 건 엄청난 장점이에요! 제약회사 연구소든 QA/QC(품질보증/품질관리) 부서든 HPLC 안 쓰는 곳은 단 한 군데도 없거든요. 아까 면접관의 생산 공정 질문에 답변하실 때는, 본인이 직접 스케일업을 안 해봤더라도 이렇게 논리를 풀어나가셔야 해요. "제가 랩실에서 HPLC 분석 조건(Method)을 잡으면서 불순물 정제 효율을 95%까지 끌어올린 경험이 있습니다. 이 분석 프로토콜은 향후 공정 개발 팀에서 대량 생산 타당성을 검증할 때 가이드라인 역할을 할 수 있으며, 생산 단계에서 발생할 수 있는 품질 불량을 모니터링하는 데 기여할 수 있습니다." 이런 식으로 나의 분석 역량이 공정의 안정성에 기여한다는 연결고리를 만들어주는 거죠.
    Guest: 와... 분석 조건 잡은 경험을 상업화 단계의 품질 모니터링이랑 연결하는 거군요. 저는 맨날 "대량 생산은 안 해봤지만 입사해서 열심히 배우겠습니다"라고만 했었는데, 그렇게 말하니까 제 장비 숙련도가 완전히 다르게 쓰일 수 있겠네요. 소름 돋았습니다. (웃음)
    Host: 하하, 면접관들이 듣고 싶어 하는 말이 바로 그거예요. "내가 가진 툴로 회사의 문제를 어떻게 풀어줄 것인가." 그리고 포트폴리오나 이력서 쓰실 때 장비 모델명까지 구체적으로 적어주시는 게 좋아요. 예를 들어 그냥 'HPLC 다룰 줄 암'이 아니라 'Agilent 1260 이나 Waters 2695 모델 가동 및 데이터 분석 가능' 이런 식으로 쓰면, 실무자들이 보고 "어, 이거 우리 방에서 쓰는 장비네? 들어오면 사수 없이 바로 장비 돌릴 수 있겠구나" 하고 서류 점수를 확 높게 줍니다.
    Guest: 아, 장비 모델명까지요! 연구실에서 매일 보던 장비인데 정작 이력서에는 대분류로만 적었었네요. 당장 내일 장비 사진 찍어둔 거 보고 모델명 다 받아 적어서 이력서 업데이트하겠습니다.
    Host: 네, 아주 사소해 보이지만 실무자들에겐 그게 진짜 경력처럼 보이거든요. (웃음) 어... 그리고 넥스트바이오 연구소 분위기에 대해서도 궁금하다고 하셨는데, 저희는 기본적으로 바이오 의약품, 그러니까 바이오시밀러랑 신약 후보 물질을 개발하는 곳이다 보니까 연구원들의 전문성을 되게 존중해 주는 편이에요. 박사님들도 많고 수평적인 토론 문화가 잘 잡혀 있습니다. 다만, 제약 산업 특성상 데이터의 신뢰성, 즉 데이터 인테그리티(Data Integrity)를 엄청나게 엄격하게 따져요. 실험 노트 하나 쓸 때도 정해진 규정에 맞춰서 써야 하고 오탈자나 데이터 조작은 절대 용납이 안 됩니다.
    Guest: 데이터 인테그리티... 대학원 연구실에서도 교수님이 항상 강조하셨던 건데 기업은 역시 훨씬 더 엄격하군요. 넵, 연구 윤리와 정직함을 강조할 수 있는 실험 노트 트러블 슈팅 경험을 자소서 3번 항목에 녹여내야겠습니다. 어... 그리고 성현 님, 이것도 취준생 입장에서 가장 현실적인 걱정인데... 혹시 넥스트바이오 석사 신입 연구원의 연봉 레인지나 복지 처우가 대략 어떻게 되는지 알 수 있을까요? 대학원 생활을 오래 하다 보니 경제적인 부분도 이제 무시를 못 하겠더라고요.
    Host: 당연히 중요하죠. 든든해야 연구도 잘 되는 법이니까요. (웃음) 저희 넥스트바이오 기준으로 말씀드리면, 학사 신입은 초봉이 4,600만 원 선이고요. 아름 님처럼 석사 학위를 소지하신 분들은 경력 2년을 인정받아서 호봉이 높게 시작해요. 그래서 석사 초봉은 기본급 기준으로 올해 대략 5,400만 원 정도 됩니다.
    Guest: 와... 5,400만 원이요? 생각했던 것보다 훨씬 대우가 좋네요!
    Host: 네, 바이오 업계가 대기업 계열사... 예를 들어 삼성바이오로직스나 셀트리온 같은 곳들이 연봉을 많이 올려놔서, 저희 같은 중견·대형 바이오텍들도 인재를 안 뺏기려고 연봉을 대기업 수준으로 많이 맞춰주는 추세예요. 그리고 연말에 신약 임상 진행 상황이나 매출 목표 달성률에 따라 성과급이 나오는데, 작년에는 연구소 전 직원한테 성과급으로 한 800만 원 정도가 일시금으로 지급됐었어요.
    Guest: 성과급 800만 원까지... 진짜 대학원생 때 한 달에 100만 원 남짓 받으면서 실험하던 시절 생각하면 눈물이 앞을 가리네요. (웃음) 정말 열심히 준비해야겠습니다. 복지 혜택은 어떤 게 있나요?
    Host: 복지는 일단 연구소 안에서 유해 물질이나 방사성 동위원소 같은 걸 다루다 보니까, 안전 관련해서 특수 건강검진을 1년에 두 번 무료로 시켜주고요. '연구 수당'이라고 해서 매달 기본급 외에 30만원씩 고정으로 연구 활동비가 통장에 따로 꽂힙니다. 그리고 석·박사 연구원들을 위해 해외 학회 참관 기회도 매년 우수 연구원들을 선발해서 비행기 표랑 호텔비 전액 지원해 주는데, 저도 작년에 미국 암학회(AACR) 다녀왔거든요. 견문 넓히기에 진짜 좋습니다.
    Guest: 매달 연구 수당 30만 원에 해외 학회 지원까지... 진짜 연구원들을 위한 맞춤형 복지네요. 오늘 성현 님 말씀 듣고 나니까 넥스트바이오에 꼭 입사해야겠다는 열정이 마구 샘솟습니다. 면접 질문 방어 전략부터 장비 모델명 팁까지 정말 돈 주고도 못 배울 조언들이었어요.
    Host: 하하, 도움이 되었다니 저도 뿌듯하네요. 아름 님은 기본 베이스가 탄탄하셔서 아까 말씀드린 '상업화 관점의 스토리텔링'과 '디테일한 장비 기술'만 서류랑 면접에 녹여내시면 하반기 공채 때 무조건 좋은 소식 있을 겁니다. 자신감 잃지 마세요. 혹시 포트폴리오 수정본 나오거나 자소서 넥스트바이오 양식에 맞춰 쓰신 거 피드백 필요하시면 편하게 제 이메일로 보내주세요. 제가 연구소 퇴근하고 틈틈이 봐 드릴게요.
    Guest: 헉, 진짜 보내드려도 괜찮을까요? 선배님 바쁘실 텐데 너무 신세 지는 것 같아서 죄송하면서도 너무 감사하네요... 메일 주소 공유 부탁드립니다!
    Host: 네, 제 회사 계정 알려드릴게요. sunghyun.choi@nextbio.com 입니다. S, U, N, G, H, Y, U, N점 C, H, O, I 골뱅이 넥스트바이오 닷컴 이고요. 메일 발송하시고 제 핸드폰 번호 010-4444-5555 로 "커피챗 진행했던 정아름입니다. 자소서 발송했습니다"라고 문자 한 통만 남겨주세요. 그럼 제가 놓치지 않고 확인해 볼게요.
    Guest: sunghyun.choi@nextbio.com 네! 오탈자 없이 정확하게 타이핑했습니다. 010-4444-5555 번호도 제 연락처에 바로 저장했습니다. 진짜 오늘 주신 소중한 시간 절대 헛되지 않게 밤새워서 이력서 뜯어고치겠습니다. 너무너무 감사드립니다, 성현 님! 꼭 합격해서 인사드리러 가겠습니다. 안녕히 계세요!
    Host: 하하, 네. 너무 무리하진 마시고요. 맛있는 저녁 드시고 푹 쉬세요. 하반기에 꼭 저희 연구소 복도에서 후배 연구원으로 만났으면 좋겠네요. 화이팅입니다! 방 종료하겠습니다.
    """
    
    try:
        step0 = agent_regex_masking(raw_text)
        step1 = agent_azure_pii(step0)
        step2 = agent_llm_masking(step1)
        final_json_str = agent_llm_summary(step2)

        final_json_str = final_json_str.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(final_json_str)

        # 💡 [핵심 1] PDF를 완벽하게 그리기 위해 원본 JSON은 서버 폴더에 몰래 저장해둡니다!
        with open(f"summary_data/{chat_id}.json", "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False)

        # 💡 [핵심 2] textarea 화면을 위해 완벽한 줄글 리포트를 조립합니다!
        meta = parsed.get("session_metadata", {})
        agendas = parsed.get("core_agendas", [])
        consensus = parsed.get("session_consensus", "내용 없음")

        pretty_text = "1. 게스트 상황 및 목표\n"
        pretty_text += f"[현재 상황]\n{meta.get('guest_as_is', '내용 없음')}\n\n"
        pretty_text += f"[목표]\n{meta.get('guest_to_be', '내용 없음')}\n\n"
        
        pretty_text += "2. 핵심 논의 안건\n"
        if agendas:
            for i, a in enumerate(agendas, 1):
                pretty_text += f"주제 {i}: {a.get('agenda_title', '')}\n"
                pretty_text += f"- 게스트 상황/질문: {a.get('guest_context', '')}\n"
                pretty_text += f"- 호스트 해결책: {a.get('host_solution', '')}\n\n"
        else:
            pretty_text += "- 등록된 안건이 없습니다.\n\n"

        pretty_text += f"3. 최종 합의점 및 결론\n{consensus}"

        # 💡 [핵심 3] DB에는 이 "예쁜 줄글"만 저장합니다. (그래서 화면에 무조건 줄글이 뜹니다!)
        if session:
            session.ai_summary = pretty_text
            db.commit()
        else:
            # session이 없으면 새로 만들어서 저장
            from models import ChatSession
            new_session = ChatSession(booking_id=chat_id, ai_summary=pretty_text)
            db.add(new_session)
            db.commit()
            
        return {"message": "요약본 생성 성공"}
    except Exception as e:
        print(f"🚨 파이프라인 에러: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/chat-session/{chat_id}/summary-pdf")
async def download_summary_pdf(chat_id: int, db: Session = Depends(get_db)):
    # 💡 아까 몰래 숨겨둔 JSON 파일을 꺼내서 PDF 생성기에 던져줍니다!
    json_file_path = f"summary_data/{chat_id}.json"
    if not os.path.exists(json_file_path):
        raise HTTPException(status_code=404, detail="요약 데이터가 없습니다. 종료 버튼을 다시 눌러주세요.")

    with open(json_file_path, "r", encoding="utf-8") as f:
        parsed = json.load(f)

    pdf_path = f"summary_{chat_id}.pdf"
    generate_pdf_report(parsed, pdf_path)
    
    return FileResponse(pdf_path, media_type="application/pdf", filename="커피챗_상세리포트.pdf")