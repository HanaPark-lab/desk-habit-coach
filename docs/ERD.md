# ERD (구현 기준)
```mermaid
erDiagram
 AUTH_USER ||--o{ ANALYSIS_JOB : requests
 ANALYSIS_JOB ||--o{ PERSON_PREDICTION : contains
 AUTH_USER ||--o{ STUDY_SESSION : owns
 AUTH_USER ||--o{ DAILY_USER_ACTIVITY : has
 STUDY_SESSION o|--o{ ANALYSIS_JOB : "optional (SET_NULL)"
 STUDY_SESSION ||--o{ STUDY_INTERVAL : contains
 AUTH_USER ||--o{ BEHAVIOR_EVENT : owns
 STUDY_SESSION o|--o{ BEHAVIOR_EVENT : "optional (SET_NULL)"
 ANALYSIS_JOB o|--o{ BEHAVIOR_EVENT : "clip source (CASCADE)"
 DAILY_USER_ACTIVITY {
 bigint id PK
 bigint user_id FK
 date day "Asia/Seoul"
 boolean logged_in
 datetime last_seen_at "nullable"
 }
 STUDY_SESSION {
 uuid id PK
 bigint user_id FK
 string status "ACTIVE/PAUSED/ENDED"
 string mode "MANUAL/AI"
 json roi "nullable, 0~1"
 datetime started_at
 datetime ended_at
 datetime last_seen_at "수동 heartbeat"
 bigint last_seq
 datetime last_observed_at "마지막 유효 관측"
 datetime presence_since "복귀 후보"
 datetime absent_since "부재 후보"
 json realtime_state "episode·마지막 기록"
 boolean phone_detection
 datetime phone_since
 }
 STUDY_INTERVAL {
 bigint id PK
 uuid session_id FK
 string state "STUDY/BREAK/AWAY/AWAY_PENDING/UNKNOWN"
 datetime started_at
 datetime ended_at
 string source "MANUAL/AUTO"
 }
 BEHAVIOR_EVENT {
 uuid id PK
 bigint user_id FK
 uuid session_id FK
 uuid job_id FK
 string action_label "실제 모델 라벨"
 string event_type "DRINK/MOVEMENT/PHONE"
 float confidence "모델 점수"
 string source "CLIP/REALTIME/FOCUS"
 string model_version
 datetime occurred_at
 string dedup_key UK
 boolean is_valid
 }
 ANALYSIS_JOB {
 uuid id PK
 bigint user_id FK
 uuid session_id FK
 string title
 text memo
 string input_type "UPLOAD/IPCAM"
 file video_file
 string camera_key "URL은 저장 안 함"
 int capture_seconds
 string status "PENDING/STARTED/SUCCESS/FAILURE"
 string celery_task_id
 string model_profile "기본 service, 기존 course 값 보존"
 string model_version
 string error_code
 text error_message
 int processing_ms
 datetime created_at
 datetime started_at
 datetime finished_at
 }
 PERSON_PREDICTION {
 bigint id PK
 uuid job_id FK
 int track_id "영상 내 번호"
 string action_label
 float confidence
 int window_count
 json probabilities
 datetime predicted_at
 }
```
## 제약 및 저장 정책
- `DailyUserActivity`: `(day, user)` 고유. 성공한 로그인 여부와 계측 대상 요청 중 마지막 접속 시각만 저장하며 사용자가 삭제되면 함께 삭제된다. 요청 경로, IP, 기기 정보는 이 모델에 저장하지 않는다. 마이그레이션은 기존 이력을 채우지 않는다.
- `PersonPrediction`: (job, track_id) unique. `AnalysisJob` 상태는 Worker만 바꾼다.
- `StudySession`: 사용자당 열린(ACTIVE·PAUSED) 세션 1개 (조건부 unique `one_open_session_per_user`).
- `StudyInterval`: 반열린 구간 [started_at, ended_at), 세션당 열린 구간 1개 (`one_open_interval_per_session`). 상태 변경은 `transaction.atomic` + `select_for_update`. 합계는 구간에서 계산.
- `BehaviorEvent.dedup_key`: 클립 `job:{id}`, 실시간 `rt:{session}:{event}:{시각}`, 휴대폰 `phone:{session}:{시각}`. 정정은 `is_valid=false`(집계 제외).
- 삭제: Job 삭제 시 예측·클립 행동 기록 CASCADE, 실행 중 Job 삭제 금지, 영상 파일은 DB commit 후 삭제. 세션 삭제 시 구간 CASCADE, 연결된 Job·행동 기록은 SET_NULL.
- Notification 테이블은 선택(P2) — 구현하지 않음.
