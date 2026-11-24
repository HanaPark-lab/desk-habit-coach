# 시스템 아키텍처 v2.0

## 전체 시스템 — Docker Compose 5개 서비스
```mermaid
flowchart TB
 B[브라우저: 타이머·카메라·대시보드]
 IP[IP Webcam]
 subgraph SYS[DESK HABIT COACH / Docker Compose]
  subgraph WEB[Django + DRF]
   API[인증·CRUD·세션 API]
   ENG[시간 계산·이벤트 중복 제거·알림]
   ORM[Django ORM]
   API --> ENG --> ORM
  end
  subgraph ASYNC[비동기 처리]
   R[Redis Broker] --> C[Celery Worker]
  end
  subgraph AI[FastAPI]
   V[영상 및 프레임 입력]
   Y[YOLO Pose / Tracking]
   F[기존 Feature / Sequence]
   RF[Random Forest 6종]
   P[착석 영역·사람 존재 판정]
   V --> Y --> F --> RF
   Y --> P
  end
  subgraph STORAGE[저장 계층]
   DB[(PostgreSQL)]
   M[(공유 Media Volume)]
  end
  API --> R
  API --> M
  C -->|클립 분석| V
  M --> V
  C -->|작업 결과 ORM 저장| DB
  API -->|실시간 샘플 요청| V
  RF -->|행동 후보 JSON| ENG
  P -->|상태 후보 JSON| ENG
  ORM <--> DB
 end
 B <-->|HTTPS / 개발 HTTP| API
 IP -->|짧은 클립 수집| C
```
위 결과 화살표는 논리적 흐름이다. 클립 결과는 FastAPI → Celery → ORM, 실시간 결과는 FastAPI → Django → ORM 경로로 반환한다. FastAPI는 DB에 직접 접근하지 않는다.

## Django 내부
```mermaid
flowchart TB
 B[Templates / JS] --> U[urls.py]
 U --> V[views.py / serializers.py / permissions.py]
 V --> J[analyses: Job CRUD]
 V --> S[study: Session service]
 V --> D[dashboard: 집계]
 J --> Q[Celery publisher]
 S --> T[시간 상태 머신]
 S --> E[행동 이벤트 서비스]
 S --> I[내부 inference client]
 T --> O[Django ORM]
 E --> O
 D --> O
 J --> O
 O --> DB[(PostgreSQL)]
```
## AI 추론 내부
```mermaid
flowchart TB
 subgraph FAST[FastAPI inference]
  IN[클립 또는 프레임] --> VAL[디코딩·품질 검사]
  VAL --> YO[YOLO Pose / Tracking]
  YO --> ROI[착석 ROI / 존재·관절 품질]
  YO --> FE[기존 38 Feature]
  FE --> BUF[사람별 30 Step buffer]
  BUF --> FL[1140D: JSON 순서]
  FL --> RF[RF predict_proba]
  RF --> AG[윈도우 집계·후보 필터]
  ROI --> OUT[상태·행동 후보 JSON]
  AG --> OUT
 end
```
클립과 실시간 입력의 tracker/buffer는 격리한다. 실시간 세션별 상태는 메모리 TTL로 관리하고 초기 배포는 FastAPI 단일 프로세스. 재시작 시 buffer 초기화 및 UNKNOWN 처리. 학습 당시 샘플링 간격을 유지할 수 없으면 행동 추론을 보류한다.

## 클립 비동기 시퀀스 (교과 필수)
```mermaid
sequenceDiagram
 participant B as Browser
 participant D as Django
 participant P as PostgreSQL
 participant R as Redis
 participant C as Celery
 participant F as FastAPI
 B->>D: MP4 또는 IP Webcam 분석
 D->>P: PENDING 생성
 D->>R: commit 후 enqueue
 D-->>B: 202 + Job ID
 R->>C: task
 C->>P: STARTED
 C->>F: 영상 참조
 alt 성공
 F-->>C: 사람별 예측
 C->>P: 원자적 결과 저장 + SUCCESS
 else 실패
 C->>P: 오류 메시지 + FAILURE
 end
 B->>D: 상태 polling
 D-->>B: 상태 및 결과
```
## 실시간 세션 시퀀스
```mermaid
sequenceDiagram
 participant B as Browser
 participant D as Django
 participant F as FastAPI
 participant P as PostgreSQL
 B->>D: 세션 시작
 D->>P: ACTIVE 생성
 loop 제한된 샘플링 / 한 요청씩
 B->>D: frame + seq
 D->>F: session key + frame
 F-->>D: presence / action candidates
 D->>P: 상태 구간·행동 이벤트 저장
 D-->>B: 시간 및 이벤트
 end
 B->>D: 종료 또는 일시정지
 D->>P: 구간 확정
```
브라우저 getUserMedia는 명시적 시작 후만 활성화. 초기에는 HTTP 샘플 전송, 동시 요청 1개, 크기·빈도 제한, timeout. 실시간 경로는 Celery 장기 작업으로 만들지 않는다. HTTPS 또는 localhost 필요. 프레임 원본은 기본 미저장. 연결 끊김은 UNKNOWN, 사용자 종료 시 카메라 track stop.

## 시간 상태 머신
```mermaid
stateDiagram-v2
 [*] --> UNKNOWN
 UNKNOWN --> STUDY: 착석 안정 확인
 STUDY --> AWAY: 자리 비움 지속
 AWAY --> STUDY: 복귀 안정 확인
 STUDY --> BREAK: 수동 휴식
 AWAY --> BREAK: 수동 휴식
 UNKNOWN --> BREAK: 수동 휴식
 BREAK --> UNKNOWN: 재개
 STUDY --> UNKNOWN: 품질 저하 또는 연결 끊김
 AWAY --> UNKNOWN: 연결 끊김
```
STUDY는 착석 기반 추정이며 실제 집중 측정 아님. 수동 휴식 우선, 종료는 모든 상태에서 가능. 상태 구간은 겹치지 않으며 서버 시간 기준으로 계산한다.

## 배포
```mermaid
flowchart TB
 B[Browser] -->|8000| D
 subgraph COMPOSE[Docker Compose / internal network]
 D[Django] --> R[Redis 6379] --> C[Celery]
 D --> F[FastAPI 8001]
 C --> F
 D --> P[PostgreSQL 5432]
 C --> P
 D --- M[(media volume)]
 C --- M
 F --- M
 F --- A[(model files read only)]
 P --- V[(postgres data)]
 end
```
Django만 외부 공개. IP Webcam은 Worker가 허용된 주소로 접속. 모델·DB·Redis 포트는 내부 전용. GPU/CPU 자원 및 동시 추론 제한을 측정한다.
