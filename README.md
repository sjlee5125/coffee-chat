# ☕ TeaTimes (Backend & AI Pipeline)

취준생과 N잡 현직자를 AI 커피챗으로 연결하는 풀사이클 커리어 플랫폼

본 레포지토리는 TeaTimes 프로젝트의 백엔드(Backend) API, AI 파이프라인, 실시간 통신 영역을 담고 있습니다.

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

## 🚀 설치 및 실행 방법

1. 저장소 클론
git clone https://github.com/sjlee5125/coffee-chat.git
cd coffee-chat

2. 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

3. 패키지 설치
pip install -r requirements.txt

4. 환경 변수 설정
.env 파일을 생성하고 DB URI, Azure API Key, OpenAI Key 등을 입력하세요.

5. 데이터베이스 마이그레이션 및 서버 실행
uvicorn main:app --reload --host 0.0.0.0 --port 8000


Frontend 레포지토리는 https://github.com/sjlee5125/teatimes-prod.git 에서 확인할 수 있습니다.
