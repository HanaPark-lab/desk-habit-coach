# ERD v2.0
```mermaid
erDiagram
 AUTH_USER ||--o{ ANALYSIS_JOB : requests
 ANALYSIS_JOB ||--o{ PERSON_PREDICTION : contains
 AUTH_USER ||--o{ STUDY_SESSION : owns
 STUDY_SESSION o|--o{ ANALYSIS_JOB : optional_link
 STUDY_SESSION ||--o{ STUDY_INTERVAL : contains
 STUDY_SESSION ||--o{ BEHAVIOR_EVENT : records
 STUDY_SESSION ||--o{ NOTIFICATION : receives
 STUDY_SESSION {
 uuid id PK
 bigint user_id FK
 string status
 datetime started_at
 datetime ended_at
 datetime last_seen_at
 int last_seq
 }
 STUDY_INTERVAL {
 bigint id PK
 uuid session_id FK
 string state
 datetime started_at
 datetime ended_at
 string source
 }
 BEHAVIOR_EVENT {
 uuid id PK
 uuid session_id FK
 string action_label
 string event_type
 float confidence
 datetime occurred_at
 string dedup_key UK
 boolean is_valid
 }
 ANALYSIS_JOB {
 uuid id PK
 bigint user_id FK
 uuid session_id FK
 string input_type
 string video_path
 string status
 string celery_task_id
 string title
 string memo
 string error_message
 datetime created_at
 datetime completed_at
 }
 PERSON_PREDICTION {
 bigint id PK
 uuid job_id FK
 int track_id
 string action_label
 float confidence
 int window_count
 }
 NOTIFICATION {
 bigint id PK
 uuid session_id FK
 string notification_type
 datetime created_at
 boolean is_read
 }
```
## 제약 및 저장 정책
- 교과 핵심 auth_user, AnalysisJob, PersonPrediction 유지. job_id+track_id unique. 상태 PENDING/STARTED/SUCCESS/FAILURE.
- StudySession: ACTIVE/PAUSED/ENDED, 사용자당 열린 세션 하나(조건부 unique). session_id가 붙은 Job도 동일 소유자만 허용.
- StudyInterval: STUDY/BREAK/AWAY/UNKNOWN, 반열린 구간 [start,end), 세션당 열린 구간 하나. 트랜잭션과 row lock으로 중복·겹침 방지. 시간 합계는 구간에서 계산(캐시 사용 시 재계산 가능).
- BehaviorEvent: DRINK/MOVEMENT, 실제 RF label 유지, confidence는 모델 점수, dedup_key는 세션·행동 episode 식별자. 사용자 정정은 is_valid 또는 별도 감사 기록. 미션 테이블 제거.
- Notification은 P2 선택. 삭제 정책은 종료된 세션만 사용자 삭제 허용, 하위 구간·이벤트 cascade; 연결된 Job은 SET_NULL. 실행 중 Job 삭제 금지. 영상 파일은 commit 후 삭제.
- 기존 DB에 미션 기록이 있다면 백업 후 별도 마이그레이션. 기존 기록을 자동으로 공부 세션으로 변환하지 않는다.
