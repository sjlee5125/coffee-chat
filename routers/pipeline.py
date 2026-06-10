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
# 🛡️ 통합 마스킹 엔진 (가명화 및 매핑)
# ==========================================
class MaskingEngine:
    def __init__(self):
        self.masking_map = {} # {'[이메일_1]': 'daeun@gmail.com'}
        self.reverse_map = {} # {'daeun@gmail.com': '[이메일_1]'}
        self.counters = {}    # {'이메일': 1}

    def _get_token(self, category, original_text):
        # 이미 등록된 단어면 같은 토큰 반환 (문맥 유지)
        if original_text in self.reverse_map:
            return self.reverse_map[original_text]
        
        # 새 단어면 카운트 올리고 새 토큰 발급
        self.counters[category] = self.counters.get(category, 0) + 1
        token = f"[{category}_{self.counters[category]}]"
        
        self.masking_map[token] = original_text
        self.reverse_map[original_text] = token
        return token

    def apply_regex(self, text):
        print("⚡ [Agent 0] Regex 가명화 가동...")
        
        # 정규식 패턴과 카테고리 정의
        patterns = [
            (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '이메일'),
            (r'01[0-9][\-\s]?\d{3,4}[\-\s]?\d{4}', '연락처'),
            (r'\d{6}[\-\s]?[1-4]\d{6}', '주민번호'),
            (r'[\d,]+(?:\s*만|\s*억|\s*천)?\s*원', '금액'),
            (r'[\d\.]+\s*%', '비율')
        ]
        
        for pattern, category in patterns:
            def replace_func(match):
                return self._get_token(category, match.group(0))
            text = re.sub(pattern, replace_func, text)
            
        return text
    
# ✨ 에러를 막기 위한 함수 래퍼 추가 (여기에 다 있습니다!)
def agent_regex_masking(text):
    return MaskingEngine().apply_regex(text)

def agent_azure_pii(text):
    return MaskingEngine().apply_azure_ner(text)

def agent_llm_masking(text):
    return text

def agent_llm_summary(safe_text):
    # 기존 요약 로직 그대로 유지
    pass

    def apply_azure_ner(self, text):
        """Azure PII는 훌륭한 엔터프라이즈용 NER(개체명 인식) 모델입니다."""
        if text_analytics_client is None:
            print("⚠️ Azure API 키가 없어 NER 마스킹을 건너뜁니다.")
            return text
            
        print("🛡️ [Agent 1] Azure NER 가명화 가동...")
        try:
            response = text_analytics_client.recognize_pii_entities([text], language="ko")[0]
            if response.is_error:
                return text
                
            # 위치(offset) 역순으로 정렬하여 텍스트 치환 시 인덱스 꼬임 방지
            entities = sorted(response.entities, key=lambda x: x.offset, reverse=True)
            for entity in entities:
                # 사람, 조직, 위치 등 민감 개체명만 토큰화
                if entity.category in ['Person', 'Organization', 'Location', 'PhoneNumber', 'Email']:
                    category_kr = "인물" if entity.category == 'Person' else \
                                  "조직" if entity.category == 'Organization' else \
                                  "위치" if entity.category == 'Location' else "기밀"
                    
                    original_text = text[entity.offset:entity.offset + entity.length]
                    token = self._get_token(category_kr, original_text)
                    
                    # 텍스트 치환
                    text = text[:entity.offset] + token + text[entity.offset + entity.length:]
            return text
        except Exception as e:
            print(f"🚨 Azure NER 에러: {e}")
            return text

def demask_text(text, masking_map):
    """LLM이 만든 요약본의 토큰을 다시 원본으로 복구합니다."""
    print("🔄 [Agent 4] 원본 텍스트 복구(De-masking) 가동...")
    for token, original in masking_map.items():
        text = text.replace(token, original)
    return text

# ==========================================
# 📝 Agent 3: LLM Summary (안전한 텍스트만 들어옵니다)
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

# PDF 생성 함수는 기존과 동일하게 유지...
def generate_pdf_report(parsed_json, output_filename):
# (이 부분은 작성자님의 기존 코드를 그대로 유지하세요)
    pass

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
