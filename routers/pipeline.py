import os
import json
from openai import OpenAI
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import TextAnalyticsClient
from dotenv import load_dotenv
load_dotenv()
LANGUAGE_ENDPOINT = os.getenv("LANGUAGE_ENDPOINT")
LANGUAGE_KEY = os.getenv("LANGUAGE_KEY")
OPENAI_ENDPOINT = os.getenv("OPENAI_ENDPOINT")
OPENAI_KEY = os.getenv("OPENAI_KEY")
text_analytics_client = TextAnalyticsClient(
    endpoint=LANGUAGE_ENDPOINT, 
    credential=AzureKeyCredential(LANGUAGE_KEY)
)
# 💡 [주의] Azure AI Foundry의 '배포 이름(Deployment Name)'과 정확히 일치해야 합니다!
MASKING_DEPLOYMENT = "gpt-4o-mini" 
SUMMARY_DEPLOYMENT = "gpt-4o"               

openai_client = OpenAI(base_url=OPENAI_ENDPOINT, api_key=OPENAI_KEY)

# ==========================================
# 🤖 Agent 1: Azure PII (보편적 개인정보 1차 방어)
# ==========================================
def agent_azure_pii(text):
    print("🛡️ [Agent 1] Azure PII 가동: 이름, 연락처, 이메일 등 기본 개인정보 차단 중...")
    try:
        response = text_analytics_client.recognize_pii_entities([text], language="ko")
        if not response[0].is_error:
            return response[0].redacted_text
    except Exception as e:
        print("🚨 Azure PII 에러:", e)
    return text

# ==========================================
# 🤖 Agent 2: LLM Masking (문맥 기반 기밀정보 2차 방어)
# ==========================================
def agent_llm_masking(text):
    print("🕵️ [Agent 2] Masking AI (mini) 가동: 14대 기업 기밀 문맥 분석 및 마스킹 중...")
    
    system_prompt = """
    당신은 IT 기업의 최고 보안 책임자(CISO)입니다. 
    주어진 텍스트를 읽고, 아래의 '기업 기밀 정보' 14가지 항목에 해당하는 단어나 문장을 찾아 '[기밀_항목명]' 형태로 마스킹(비식별화)하세요.
    
    [마스킹 대상]
    1. 금액: 원, 만원, 억원 등 재무/결제 금액 (예: 1,500만 원 -> [기밀_금액])
    2. 퍼센트/비율: 마진율, 전환율 등 수치 (예: 45% -> [기밀_비율])
    3. 내부 프로젝트명: 진행 중인 프로젝트 이름 (예: 프로젝트 오리온 -> [기밀_프로젝트])
    4. 서비스 핵심 지표: DAU, MAU, 가입자 수, 트래픽 등 (예: DAU 50만 명 -> [기밀_지표])
    5. 투자 라운드: 시리즈 A, 시드 투자 등 (예: 시리즈B 준비 -> [기밀_투자라운드])
    6. 팀/조직 인원 규모: 특정 부서의 인원수 (예: 백엔드팀 15명 -> [기밀_조직규모])
    7. 인사평가/고과: 평가 등급 (예: 고과 S등급 -> [기밀_인사평가])
    8. 미공개 B2B 고객사 및 파트너: 계약, MOU, 납품 파트너 (예: 테슬라와 계약 -> [기밀_고객사]와 계약)
    9. 미공개 출시 일정 및 로드맵: 런칭, 오픈 일정 (예: 3분기 런칭 -> [기밀_일정])
    10. 인수합병(M&A) 및 상장(IPO): 상장, 인수 실사 등 (예: 코스닥 상장 준비 -> [기밀_M&A/IPO])
    11. IT 인프라 전환 및 보안 이슈: 클라우드 마이그레이션, 해킹, 랜섬웨어 등 (예: AWS로 이관, 랜섬웨어 감염 -> [기밀_보안/인프라])
    12. 개인/조직 보상: 연봉, 스톡옵션, 인센티브 등 (예: 연봉 8천, 스톡옵션 100주 -> [기밀_보상정보])
    13. 인증/크레덴셜: API 키, 토큰, 비밀번호 등 (예: AWS 시크릿 키 -> [기밀_인증정보])
    14. 미공개 특허 및 핵심 기술: 독자적 알고리즘, 출원 전 특허 등 (예: 새로 개발한 추천 알고리즘 -> [기밀_특허/기술])
    15. 개인 신상 및 소속 정보: 대학교, 대학원, 현재 직장명, 이전 직장명 등 개인의 소속을 특정할 수 있는 고유명사 (예: 한국대학교, 스타브릿지 엔터테인먼트 -> [기밀_소속정보])
    
    [주의사항]
    - 절대 텍스트의 내용을 요약하거나 지어내지 마세요.
    - 기밀 정보만 치환하고, 나머지 대화 내용과 형식(Host:, Guest:)은 원본 그대로 100% 유지하여 출력하세요.
    - 맥락상 일반적인 대화이거나 확신할 수 없는 정보라면 과도하게 마스킹하지 말고 원문을 유지하세요.
    """
    
    try:
        response = openai_client.chat.completions.create(
            model=MASKING_DEPLOYMENT,
            temperature=0.0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print("🚨 Masking AI 에러:", e)
        return text

# ==========================================
# 🤖 Agent 3: LLM Summary (안전한 데이터로 최종 요약)
# ==========================================
def agent_llm_summary(safe_text):
    print("📝 [Agent 3] Summary AI (4o) 가동: 비식별화된 데이터로 고품질 요약 리포트 생성 중...")
    
    system_prompt = """
    당신은 IT/비즈니스 커피챗 대화를 분석하는 전문 에디터입니다.
    제공된 STT 대화 스크립트(이미 마스킹 완료됨)를 분석하여 아래 JSON 구조에 맞게 빈틈없이 채워주세요.

    [출력 JSON 포맷]
    {
      "masked_full_text": "원본 텍스트 그대로 출력 (발화자 변경 시 \n 적용)",
      "summary_report": {
        "1_mentee_background": "멘티 배경 3~5문장 서술",
        "2_core_discussions": [
          {
            "topic": "논의 주제",
            "mentee_question": "멘티 질문",
            "mentor_insight": "멘토 조언",
            "real_world_example": "실무 예시"
          }
        ],
        "3_actionable_advice": ["액션 아이템 1", "액션 아이템 2"],
        "4_overall_conclusion": "종합 결론"
      }
    }
    """
    try:
        response = openai_client.chat.completions.create(
            model=SUMMARY_DEPLOYMENT,
            response_format={ "type": "json_object" }, 
            temperature=0.3,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": safe_text}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

# ==========================================
# 🚀 메인 실행 파이프라인 (다중 파일 출력 버젼)
# ==========================================
if __name__ == "__main__":
    input_filename = "dummy.txt"
    
    print("\n[🚀 커피챗 데이터 보안 및 요약 파이프라인 시작]\n")
    
    # 1. 파일 읽기 검증
    if not os.path.exists(input_filename):
        print(f"🚨 에러: '{input_filename}' 파일이 현재 디렉토리에 존재하지 않습니다.")
        print("테스트용 샘플 텍스트로 대체하여 실행합니다.\n")
        sample_text = """
        Host: 안녕하세요 이다은 님, 한국대학교 졸업하시고 스타브릿지 엔터테인먼트에 입사하셨다고 들었어요. 연락처는 010-1234-5678 맞으시죠?
        Guest: 네 맞습니다. 강민준 멘토님! 제 개인 메일 daeun.lee@gmail.com 로도 자료 부탁드릴게요. 
        사실 제가 최근에 비밀리에 진행 중인 '프로젝트 오리온' 기획을 맡았는데요. 이번에 삼성전자와 MOU 맺으면서 DAU가 50만 명을 돌파했습니다!
        Host: 와, 대단하시네요. 혹시 팀 규모나 처우는 어떤가요?
        Guest: 백엔드팀 15명 정도 규모고요, 이번에 고과 S등급 받아서 연봉 8천만 원에 스톡옵션 100주 받기로 했습니다. 
        근데 걱정인 게, 다음 달 3분기 런칭 예정인데 어제 랜섬웨어 감염돼서 AWS 시크릿 키가 털릴 뻔했어요. 
        Host: 큰일 날 뻔했네요. 코스닥 상장 준비하시려면 보안이 생명입니다.
        Guest: 네, 저희가 이번에 독자적으로 개발한 딥러닝 추천 알고리즘 특허 출원도 앞두고 있어서요. 내년에 시리즈 B 투자 라운드 돌려면 마진율 40% 이상은 꼭 방어해야 합니다.
        """
    else:
        with open(input_filename, "r", encoding="utf-8") as f:
            sample_text = f.read()
        print(f"📖 '{input_filename}' 파일로부터 텍스트를 성공적으로 읽어왔습니다.")
    
    # 1단계: Azure PII
    step1_text = agent_azure_pii(sample_text)
    
    # 2단계: Masking AI mini
    step2_text = agent_llm_masking(step1_text)
    
    # 3단계: Summary AI 4o
    final_json_str = agent_llm_summary(step2_text)
    
    # 결과 출력 및 개별 파일 저장
    print("\n✅ 파이프라인 처리 완료! 다운로드용 파일 생성 중...\n")
    try:
        parsed_json = json.loads(final_json_str)
        
        masked_text = parsed_json.get("masked_full_text", step2_text)
        summary_data = parsed_json.get("summary_report", {})
        
        # 💾 1. 원본 대화 파일 (멘토/멘티 제공용 .txt)
        txt_filename = "masked_original_chat.txt"
        with open(txt_filename, "w", encoding="utf-8") as out_f:
            out_f.write("====== [비식별화 대화 원본] ======\n\n")
            out_f.write(masked_text)
            
        # 💾 2. 요약 리포트 파일 (멘토/멘티 가독성 고려한 Markdown 형식 .md)
        md_filename = "masked_summary_report.md"
        with open(md_filename, "w", encoding="utf-8") as out_f:
            out_f.write("# ☕ 커피챗 상세 요약 리포트\n\n")
            
            out_f.write("## 1. 멘티 배경\n")
            out_f.write(summary_data.get("1_mentee_background", "내용 없음") + "\n\n")
            
            out_f.write("## 2. 핵심 논의 사항\n")
            for i, disc in enumerate(summary_data.get("2_core_discussions", []), 1):
                out_f.write(f"### 주제 {i}: {disc.get('topic', '')}\n")
                out_f.write(f"- **멘티 질문:** {disc.get('mentee_question', '')}\n")
                out_f.write(f"- **멘토 조언:** {disc.get('mentor_insight', '')}\n")
                out_f.write(f"- **실무 예시:** {disc.get('real_world_example', '')}\n\n")
                
            out_f.write("## 3. 액션 아이템 (Actionable Advice)\n")
            for i, advice in enumerate(summary_data.get("3_actionable_advice", []), 1):
                out_f.write(f"{i}. {advice}\n")
            out_f.write("\n")
            
            out_f.write("## 4. 종합 결론\n")
            out_f.write(summary_data.get("4_overall_conclusion", "내용 없음") + "\n")

        # 💾 3. 프론트엔드 API/DB 연동용 순수 JSON (기존 유지)
        json_filename = "secure_summary_result.json"
        with open(json_filename, "w", encoding="utf-8") as out_f:
            json.dump(parsed_json, out_f, ensure_ascii=False, indent=4)
            
        print(f"🎉 [성공] 사용자 제공 및 프론트엔드 연동을 위한 3개의 파일이 생성되었습니다!")
        print(f"  📄 1) {txt_filename} (멘토/멘티 다운로드용: 마스킹된 대화 텍스트)")
        print(f"  📄 2) {md_filename} (멘토/멘티 다운로드용: 보기 좋게 정리된 요약 리포트)")
        print(f"  ⚙️ 3) {json_filename} (프론트엔드/DB 연동용: 구조화된 JSON 원본 데이터)\n")
        
    except Exception as e:
        print("🚨 파싱 또는 파일 저장 중 에러 발생:", e)