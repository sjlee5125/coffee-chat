# 커피챗 프로젝트 (Coffee Chat) - Backend

## 💡 프로젝트 소개
사용자 간의 커피챗 예약을 관리하고 안정적인 매칭 서비스를 제공하는 백엔드 서버입니다.

## 🛠 기술 스택
- **Language:** Python
- **Infrastructure:** Docker
- **Package Management:** pipreqs
- **Task Scheduling:** apscheduler

## 🚀 주요 기능
- **예약 및 노쇼(No-Show) 관리:** `apscheduler`를 활용하여 예약된 시간에 맞춘 스케줄링 및 노쇼 자동 관리 기능 구현
- **컨테이너 기반 서버 환경:** Docker를 활용한 독립적이고 안정적인 서버 구동 및 배포 환경 구성

## 🔧 주요 트러블슈팅 및 기술적 의사결정
- **스케줄러 작동 최적화:** `apscheduler` 작업 실행 시 지속해서 발생하던 경고성 스케줄러 로그를 분석하고 해결하여 안정적인 백그라운드 작업 환경 확보
- **의존성 및 빌드 최적화:** `pipreqs`를 사용하여 패키지를 스캔하고 `requirements.txt`를 체계적으로 관리하였으며, 이를 통해 도커 컨테이너 빌드 과정을 최적화하고 서버 구동의 안정성 향상
