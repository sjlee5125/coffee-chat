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

# 💡 최상단에서 환경변수 로드
load_dotenv()
logging.getLogger('fontTools.subset').setLevel(logging.ERROR)

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ImportError:
    print("🚨 fpdf2 없음. 터미널에서 pip install fpdf2 를 실행해주세요.")

# ==========================================
# 🔑 1. API 키 및 엔드포인트 세팅 (방어 로직 적용)
# ==========================================
LANGUAGE_ENDPOINT = os.environ.get("LANGUAGE_ENDPOINT")
LANGUAGE_KEY = os.environ.get("LANGUAGE_KEY")

text_analytics_client = None
if LANGUAGE_KEY and LANGUAGE_ENDPOINT:
    text_analytics_client = TextAnalyticsClient(
        endpoint=LANGUAGE_ENDPOINT, 
        credential=AzureKeyCredential(LANGUAGE_KEY)
    )

AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4o-2")
AZURE_API_VERSION = os.environ.get("AZURE_API_VERSION", "2024-12-01-preview")

SUMMARY_DEPLOYMENT = "gpt-4o"

openai_client = None
if AZURE_OPENAI_KEY:
    openai_client = AzureOpenAI(
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )

# ==========================================
# 🛡️ 2. 통합 마스킹 엔진 (가명화 및 복원)
# ==========================================
class MaskingEngine:
    def __init__(self):
        self.masking_map = {} # {'[조직_1]': '스타브릿지 엔터테인먼트'}
        self.reverse_map = {} # {'스타브릿지 엔터테인먼트': '[조직_1]'}
        self.counters = {}    # {'조직': 1}

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
    
    def apply_azure_ner(self, text):
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
                if entity.category in ['Person', 'Organization', 'Location', 'PhoneNumber', 'Email']:
                    category_kr = "인물" if entity.category == 'Person' else \
                                  "조직" if entity.category == 'Organization' else \
                                  "위치" if entity.category == 'Location' else "기밀"
                    
                    original_text = text[entity.offset:entity.offset + entity.length]
                    token = self._get_token(category_kr, original_text)
                    
                    text = text[:entity.offset] + token + text[entity.offset + entity.length:]
            return text
        except Exception as e:
            print(f"🚨 Azure NER 에러: {e}")
            return text

    def demask_text(self, text):
        """저장된 맵을 사용하여 복원 작업을 수행합니다."""
        print("🔄 [Agent 4] 원본 텍스트 복구(De-masking) 가동...")
        # 토큰 길이 순으로 내림차순 정렬하여 치환 오류 방지 (예: [조직_10]이 [조직_1]보다 먼저 바뀌도록)
        sorted_tokens = sorted(self.masking_map.items(), key=lambda x: len(x[0]), reverse=True)
        for token, original in sorted_tokens:
            text = text.replace(token, original)
        return text


# ✨ 외부 래퍼 함수들 (하위 호환성 유지)
def agent_regex_masking(text):
    return MaskingEngine().apply_regex(text)

def agent_azure_pii(text):
    return MaskingEngine().apply_azure_ner(text)

def agent_llm_masking(text):
    return text

#llm summary
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
        if not openai_client:
            return '{"error": "Azure OpenAI 클라이언트가 설정되지 않았습니다."}'
            
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
        return f'{{"error": "LLM 요약 중 에러 발생: {str(e)}"}}'


# ==========================================
# 📊 4. PDF 생성
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