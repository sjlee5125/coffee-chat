import os
import json
import re
import time
import logging
from openai import OpenAI
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import TextAnalyticsClient
from dotenv import load_dotenv

# 💡 [추가] .env 파일에서 환경 변수(비밀번호들)를 불러와서 시스템에 등록합니다.
load_dotenv()

logging.getLogger('fontTools.subset').setLevel(logging.ERROR)

# 💡 PDF 생성을 위한 라이브러리
try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ImportError:
    print("🚨 fpdf2 라이브러리가 없습니다. 터미널에서 'pip install fpdf2'를 실행해 주세요.")
    exit()

# ==========================================
# 🔑 1. API 키 및 엔드포인트 세팅
# ==========================================
LANGUAGE_ENDPOINT = os.environ.get("LANGUAGE_ENDPOINT")
LANGUAGE_KEY = os.environ.get("LANGUAGE_KEY")
text_analytics_client = TextAnalyticsClient(endpoint=LANGUAGE_ENDPOINT, credential=AzureKeyCredential(LANGUAGE_KEY))

OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT")
OPENAI_KEY = os.environ.get("OPENAI_KEY")

MASKING_DEPLOYMENT = "gpt-4o-mini" 
SUMMARY_DEPLOYMENT = "gpt-4o"               

openai_client = OpenAI(base_url=OPENAI_ENDPOINT, api_key=OPENAI_KEY)

# ==========================================
# ⚡ Agent 0: Regex Masking (14대 패턴 + 기본 개인정보 철통 방어)
# ==========================================
def agent_regex_masking(text):
    print("⚡ [Agent 0] Regex 가동: 14대 패턴 및 필수 개인정보 0.1초 마스킹 중...")
    
    # [추가] 0. 기본 개인정보 무조건 썰기
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
# 🛡️ Agent 1: Azure PII (에러 대비 재시도 로직 탑재)
# ==========================================
def agent_azure_pii(text):
    print("🛡️ [Agent 1] Azure PII 가동: 남은 개인정보 싹쓸이 중...")
    max_retries = 3 
    
    for attempt in range(max_retries):
        try:
            response = text_analytics_client.recognize_pii_entities([text], language="ko")
            if not response[0].is_error:
                return response[0].redacted_text
            else:
                print(f"⚠️ Azure 내부 에러 발생: {response[0].error.message}")
                
        except Exception as e:
            error_msg = str(e)
            print(f"🚨 Azure PII 호출 에러 (시도 {attempt + 1}/{max_retries})")
            
            if "429" in error_msg or "Too Many Requests" in error_msg:
                print("⏳ 호출 한도 초과! 3초 대기 후 다시 시도합니다...")
                time.sleep(3)
            else:
                print(f"⏳ 일시적 오류! 2초 대기 후 다시 시도합니다... ({error_msg[:50]})")
                time.sleep(2)
                
    print("❌ [경고] Azure PII가 완전히 응답하지 않습니다. Agent 0(정규식)과 Agent 2(LLM)가 대신 방어합니다!")
    return text

# ==========================================
# 🕵️ Agent 2: LLM JSON Masking (Azure 누락분 + 문맥 기밀 핀셋 마스킹)
# ==========================================
def agent_llm_masking(text):
    print("🕵️ [Agent 2] Masking AI (mini) 가동: 문맥 기밀 및 누락된 이름 핀셋 추출 중...")
    
    system_prompt = """
    당신은 IT 기업의 최고 보안 책임자(CISO)입니다. 
    제공된 텍스트는 1차적으로 개인정보와 일부 기밀이 마스킹되어 있습니다. 
    문맥을 파악하여 아래의 '잔여 기밀 정보'를 찾아내세요.
    
    [잔여 마스킹 대상]
    1. 학교, 특정 대학교, 대학원 등 개인 학력 정보
    2. 현재 직장명, 이전 직장명 등 소속 고유명사 (예: 스타브릿지 엔터테인먼트)
    3. 구체적인 보상 및 처우 (예: 연봉 8천, 스톡옵션 100주)
    4. 미공개 특허 및 핵심 기술 (예: 딥러닝 추천 알고리즘 특허)
    5. 인증/크레덴셜 (예: AWS 시크릿 키)
    6. 사람 이름 (예: 이다은, 강민준 등 앞 단계에서 실수로 누락된 모든 실명)
    7. 음차/변형된 개인정보: 스펠링을 끊어 말하거나 '골뱅이', '닷', '점' 등으로 우회하여 표현한 이메일, 전화번호, 영문 이름 등
    [출력 형식 - 매우 중요]
    전체 텍스트나 긴 문장을 절대 다시 쓰지 마세요!! 
    "original" 값에는 문장이 아니라 딱 바꿀 '짧은 단어'나 '구절'만 넣으세요.
    반드시 아래 JSON 배열 형식으로만 출력하세요.
    {
      "replacements": [
        {"original": "한국대학교", "masked": "[기밀_학교]"}
      ]
    }
    """
    try:
        response = openai_client.chat.completions.create(
            model=MASKING_DEPLOYMENT,
            response_format={ "type": "json_object" },
            temperature=0.0,
            max_tokens=10000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"출력은 반드시 'replacements'라는 키를 가진 JSON 객체로 주세요.\n\n{text}"}
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
# 📝 Agent 3: LLM Summary (호스트/게스트 용어 완벽 반영)
# ==========================================
def agent_llm_summary(safe_text):
    print("📝 [Agent 3] Summary AI (4o) 가동: 호스트/게스트 맞춤형 요약 리포트 생성 중...")
    
    # 💡 [오류 수정] 마지막에 닫는 따옴표 """ 추가 완료!
    system_prompt = """
    # Role
    당신은 커피챗 매칭 플랫폼 'Lunching'의 [수석 데이터 아키텍트(Data Architect) 및 전문 아키비스트]입니다.
    당신의 역할은 방대하고 정제되지 않은 커피챗 대화 스크립트에서 '객관적 사실, 논의된 전략, 실무 프레임워크'만을 완벽하게 발라내어, MECE(중복 없이 누락 없이) 원칙에 따라 구조화된 JSON 리포트로 변환하는 것입니다. 

    # Tone & Manner (매우 중요: Advice 에이전트와의 역할 분리)
    - 철저하게 '객관적이고 건조한 3인칭 관찰자' 시점을 유지하세요. 감정적 공감, 주관적 해석, "앞으로 이렇게 하세요" 식의 조언이나 행동 촉구(Next Step)는 절대 포함하지 마세요.
    - 대화에 등장한 직무/산업 특화 용어를 그대로 보존하되, 프로페셔널한 비즈니스 문서 톤(예: "~음", "~함" 등 명사형 종결 권장)으로 정제하여 작성하세요.

    # Output Structure (JSON Schema)
    대화의 뉘앙스와 전문성이 잘 드러나도록 해당 직무의 특성을 살려 아래 JSON 구조를 엄격하게 채워주세요. 각 Value는 최소 3~4문장의 풍부한 디테일과 실무적 맥락을 포함해야 합니다.

    {
    "session_metadata": {
        "industry_and_role": "대화에서 파악된 주요 산업군 및 두 발화자의 직무",
        "guest_as_is": "게스트의 현재 상황, 보유한 기술 스택, 그리고 마주한 객관적 병목(Pain-point) 상황",
        "guest_to_be": "대화에서 드러난 게스트의 단기적/장기적 목표"
    },
    "core_agendas": [
        {
        "agenda_title": "핵심 논의 안건 1",
        "guest_context": "게스트가 언급한 구체적인 질문, 시도했던 방법, 직면한 한계점 (객관적 사실 위주)",
        "host_solution": "호스트가 제시한 실무적 해결책 및 사용된 프레임워크 (조언의 형태가 아닌 '제시된 사실과 방법론' 위주로 서술)"
        }
    ],
    "extracted_keywords": {
        "tools_and_skills": ["대화 중 언급된 특정 툴, 프로그램, 언어, 자격증 등 하드스킬 키워드 배열"],
        "business_terms": ["KPI, MAU, 애자일 등 대화에 등장한 비즈니스/실무 용어 배열"]
    },
    "session_consensus": "오늘 대화에서 두 사람이 도달한 최종적인 합의점이나 객관적 결론"
    }
    """
    try:
        response = openai_client.chat.completions.create(
            model=SUMMARY_DEPLOYMENT,
            response_format={ "type": "json_object" }, 
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
# 📊 PDF 생성 유틸리티 (바뀐 프롬프트 구조 완벽 반영)
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

    # 제목
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

    # 1. 게스트 배경 및 상황
    meta = parsed_json.get("session_metadata", {})
    bg_content = f"[현재 상황]\n{meta.get('guest_as_is', '')}\n\n[목표]\n{meta.get('guest_to_be', '')}"
    write_section("1. 게스트 상황 및 목표", bg_content)
    
    # 2. 핵심 논의 사항
    pdf.set_font("Malgun", "B", 14)
    pdf.cell(0, 10, "2. 핵심 논의 안건", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    for i, disc in enumerate(parsed_json.get("core_agendas", []), 1):
        pdf.set_font("Malgun", "B", 12)
        safe_print_text(f"📌 주제 {i}: {disc.get('agenda_title', '')}")
        pdf.set_font("Malgun", "", 11)
        safe_print_text(f"- 게스트 상황/질문: {disc.get('guest_context', '')}")
        safe_print_text(f"- 호스트 해결책: {disc.get('host_solution', '')}")
        pdf.ln(3)

    # 💡 3번 섹션(실무 핵심 방법론 및 용어) 호출 부분을 삭제했습니다.

    # 4. 종합 결론 (번호를 3번으로 수정)
    write_section("3. 최종 합의점 및 결론", parsed_json.get("session_consensus", ""))
    
    pdf.output(output_filename)

# ==========================================
# 🚀 메인 실행부
# ==========================================
if __name__ == "__main__":
    input_filename = "dummy.txt"
    print("\n[🚀 초고속 무결점 보안 파이프라인 시작]\n")
    
    sample_text = """
    Host: 안녕하세요 이다은 님, 한국대학교 졸업하시고 스타브릿지 엔터테인먼트에 입사하셨다고 들었어요. 연락처는 010-1234-5678 맞으시죠?
    Guest: 네 맞습니다. 강민준 호스트님! 제 개인 메일 daeun.lee@gmail.com 로도 자료 부탁드릴게요. 
    사실 제가 최근에 비밀리에 진행 중인 '프로젝트 오리온' 기획을 맡았는데요. 이번에 삼성전자와 MOU 맺으면서 DAU가 50만 명을 돌파했습니다!
    Host: 와, 대단하시네요. 혹시 팀 규모나 처우는 어떤가요?
    Guest: 백엔드팀 15명 정도 규모고요, 이번에 고과 S등급 받아서 연봉 8천만 원에 스톡옵션 100주 받기로 했습니다. 
    근데 걱정인 게, 다음 달 3분기 런칭 예정인데 어제 랜섬웨어 감염돼서 AWS 시크릿 키가 털릴 뻔했어요. 
    Host: 큰일 날 뻔했네요. 코스닥 상장 준비하시려면 보안이 생명입니다.
    Guest: 네, 저희가 이번에 독자적으로 개발한 딥러닝 추천 알고리즘 특허 출원도 앞두고 있어서요. 내년에 시리즈 B 투자 라운드 돌려면 마진율 40% 이상은 꼭 방어해야 합니다.
    """
    
    if os.path.exists(input_filename):
        with open(input_filename, "r", encoding="utf-8") as f:
            sample_text = f.read()
    
    # 초고속 필터링 체인
    step0_text = agent_regex_masking(sample_text)
    step1_text = agent_azure_pii(step0_text)
    step2_text = agent_llm_masking(step1_text)
    
    # 최종 요약
    final_json_str = agent_llm_summary(step2_text)
    
    # 💡 [오류 수정] 들여쓰기 원상 복구! (앞으로 땡김)
    print("\n✅ 파이프라인 처리 완료! 파일 생성 중...\n")
    try:
        parsed_json = json.loads(final_json_str)
        
        # 1. TXT 저장
        with open("masked_original_chat.txt", "w", encoding="utf-8") as out_f:
            out_f.write("====== [비식별화 대화 원본] ======\n\n")
            formatted_text = re.sub(r'(Host:|Guest:|호스트:|게스트:)', r'\n\n\1', step2_text)
            formatted_text = re.sub(r'\n{3,}', '\n\n', formatted_text).strip()
            out_f.write(formatted_text)
            
        # 2. PDF 저장
        generate_pdf_report(parsed_json, "masked_summary_report.pdf")

        # 3. JSON 저장
        with open("secure_summary_result.json", "w", encoding="utf-8") as out_f:
            json.dump(parsed_json, out_f, ensure_ascii=False, indent=4)
            
        print("🎉 [대성공] 모든 파일(.txt, .pdf, .json)이 안전하게 생성되었습니다! 수고하셨습니다!")
        
    except Exception as e:
        print("🚨 시스템 에러 발생:", e)