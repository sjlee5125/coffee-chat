# ☕ TeaTimes (Backend & AI Pipeline)

취준생과 N잡 현직자를 AI 커피챗으로 연결하는 풀사이클 커리어 플랫폼

본 레포지토리는 TeaTimes 프로젝트의 백엔드(Backend) API, AI 파이프라인, 실시간 통신 영역을 담고 있습니다.

---

## 📺 프로젝트 핵심 자료
- **🎥 [서비스 통합 시연 영상 보러가기](https://www.youtube.com/watch?v=IlpLFsgf6fc)**
- **💻 연동되는 Frontend 레포지토리 주소**: `[https://github.com/q2qeq/teatimes](https://github.com/q2qeq/teatimes)`

---

## 📌 서비스 아키텍처 개요

TeaTimes 백엔드는 FastAPI의 비동기 처리 능력을 기반으로 실시간 대화(WebSocket)와 무거운 AI 추론 작업을 동시에 처리합니다. 특히 외부 LLM 모델(GPT-4o) 사용 시 발생할 수 있는 개인정보 유출을 원천 차단하기 위해 Azure PII 기반의 데이터 마스킹 및 복원 파이프라인을 고도화하여 구축했습니다.

## ✨ 주요 기능 및 AI 파이프라인

- RESTful API & 인증: FastAPI 기반의 고성능 API, JWT(python-jose), Bcrypt 암호화, 역할 기반(게스트/호스트) 권한 통제

- 실시간 WebSocket 서버: websockets를 활용하여 실시간 STT 텍스트 스트리밍 및 문맥 기반 AI 추천 질문 푸시

- 보안 중심의 LLM 요약 파이프라인 (Data Masking) 🛡️

+ STT: Azure Speech SDK로 실시간 음성 데이터를 텍스트로 변환

- Masking: Azure AI Text Analytics PII를 통해 텍스트 내 민감 정보(이름, 연락처 등)를 식별 및 임시 토큰으로 치환

- LLM Inference: 마스킹된 안전한 텍스트로 GPT-4o 분석 및 요약 수행

- Mapping: Custom Regular Expression Mapping Engine으로 요약본의 토큰을 원본 데이터로 복원

- 리포트 자동 생성: weasyprint와 fpdf2를 활용하여 AI 요약본과 어드바이스를 PDF 리포트로 렌더링

- 비동기 스케줄링: apscheduler를 활용한 커피챗 예약 리마인더 알림 처리

## 🛠 기술 스택 (Tech Stack)

Framework/Language: Python 3.11+, FastAPI, Uvicorn

Database & ORM: PostgreSQL, SQLAlchemy (Async), PyMySQL

AI & Cloud Services:

Azure Cognitive Services Speech SDK (STT)

Azure AI Text Analytics (PII Masking)

Azure Search Documents (RAG/Vector Search)

OpenAI API (GPT-4o)

Real-time & Utils: WebSockets, Passlib (Auth), WeasyPrint (PDF)



## 🚀 설치 및 로컬 실행 방법

> ⚠️ **중요: 로컬 구동을 위한 필수 설정 안내 (Notice)**
> - Microsoft 아카데미 지원 기간 종료로 인해 외부 Azure 및 OpenAI API 리소스가 만료된 상태입니다.
> - 로컬 환경에서 실행 시 API Credentials 누락 에러(`OpenAIError`) 및 PDF 라이브러리 미설치 에러(`OSError`)를 방지하고, 코드 검토 및 API 엔드포인트 확인을 위해 **반드시 아래 2가지 사전 세팅을 진행**해 주세요.

### [필수] 로컬 실행을 위한 사전 세팅
1. **가짜 환경변수 파일(.env) 생성**
   - 프로젝트 루트 디렉토리(main.py가 있는 위치)에 `.env` 파일을 생성하고 아래 내용을 그대로 붙여넣어 저장합니다. (※ 가짜 값을 넣어두어야 초기 서버 구동 에러를 우회할 수 있습니다.)
   ```text
   AZURE_OPENAI_API_KEY=dummy_key_for_local_test
   AZURE_OPENAI_ENDPOINT=[https://dummy-endpoint.openai.azure.com/](https://dummy-endpoint.openai.azure.com/)
   OPENAI_API_VERSION=2024-02-15-preview
   AZURE_OPENAI_DEPLOYMENT_NAME=dummy_deployment
   
```bash
1. 저장소 클론 및 가상환경 설정
git clone https://github.com/sjlee5125/coffee-chat.gitcd coffee-chat
python -m venv venv
venv\Scripts\activate  # Windows 환경

2. 패키지 설치
pip install -r requirements.txt

윈도우 환경에서 인코딩 에러(UnicodeDecodeError) 발생 시 아래 명령어로 설치 진행
python -X utf8 -m pip install -r requirements.txt

3. 로컬 서버 실행
uvicorn main:app --reload

#⚠️ 윈도우 로컬 환경 실행 시 주의사항 (OSError 해결)
본 프로젝트는 커피챗 종료 후 PDF 리포트를 생성하기 위해 `WeasyPrint` 라이브러리를 사용합니다. 
윈도우 로컬 환경에서 시스템 라이브러리(`GTK+`) 미설치로 인해 서버 실행 시 `OSError: cannot load library 'libgobject-2.0-0'` 에러가 발생하며 서버 구동이 실패할 수 있습니다.

[해결 방법 — 딱 2개 파일만 주석 처리하기]
로컬에서 에러 없이 백엔드 서버를 구동하여 프론트엔드 연동 테스트를 진행하시려면, 아래 2개 파일의 해당 라인 앞에 `#`을 붙여 주석 처리해 주세요.

1. `routers/reports.py` 파일 열기
   - 7번째 줄: `from weasyprint import HTML` ➡️ `# from weasyprint import HTML`

2. `routers/chat_router.py` 파일 열기
   - 4번째 줄: `from .reports import create_and_upload_report_pdf` ➡️ `# from .reports import create_and_upload_report_pdf`
