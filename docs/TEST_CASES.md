# 테스트 결과 (2026-11-24)

실행 명령 (프로젝트 폴더, WSL):
```bash
cd backend && ../.venv/bin/python manage.py test        # Django 81개 — OK
cd ai_service && ../.venv/bin/python -m pytest -q       # FastAPI 18개 — passed
```
상태: **통과** = 자동 테스트 또는 직접 실행으로 확인 · **부분** = 일부만 확인 · **미검증** = 실행하지 않음.

## 교과 필수
| ID | 통과 기준 | 상태 | 근거 |
|---|---|---|---|
| T01 | 모델 클래스·1140 feature·JSON 일치 | 부분 | service 4종 통과(`test_model_profiles`, `test_health`). **교과 6종(course)은 모델 파일이 없어 미검증** |
| T02 | MP4 업로드 후 사람별 결과 | 통과 | `test_people_video`, `AnalyzeTaskTests`, Docker E2E(업로드→Celery→FastAPI→DB) |
| T03 | IP Webcam 짧은 클립 수집·분석 | 부분 | 가짜 카메라로 수집·중계 테스트 통과. 실제 DroidCam은 이전 수동 실행에서만 확인 |
| T04 | 다중 인물 Track ID별 결과 | 통과 | `test_people_video`(bus.jpg 여러 명), 개인 기록 보류 `test_multiple_people_hold_personal_record` |
| T05 | 비동기 작업 ID 즉시 반환 | 통과 | `test_upload_creates_pending_job_and_queues_it` (202) |
| T06 | PostgreSQL 작업·예측 영구 저장 | 통과 | Docker E2E 작업 SUCCESS 저장 확인 |
| T07 | 사용자 A/B 격리 | 통과 | `test_other_users_job_is_invisible`, `test_other_users_session_is_invisible` |
| T08 | 관리자 목록·상태 차트 | 통과 | `test_staff_dashboard_uses_real_db_counts` |
| T09 | 실패 메시지·FAILURE 저장 | 통과 | 잘못된 파일, AI 다운, 큐 다운, 결과 저장 오류, 중단 작업 정산 테스트 |
| T10 | Docker 재시작 후 DB 유지 | 통과 | `docker compose down` → `up` 후 작업 23건 유지 확인 |

## 공부 세션·행동
| ID | 통과 기준 | 상태 | 근거 |
|---|---|---|---|
| S01 | 세션 시작·종료, 카메라 해제 | 부분 | API·엔진 통과. 페이지 이탈 시 카메라 정지는 브라우저 미검증 |
| S02 | 자리 비움·복귀 자동 전이 | 통과 | `AiModeTests`, `BreakRuleTests` |
| S03 | 수동 휴식 우선, 재개 시 UNKNOWN | 통과 | `test_break_is_manual_and_resume_enters_unknown`, B08 |
| S04 | 끊김·가림은 UNKNOWN, 과대 누적 방지 | 통과 | `test_unclear_frames_and_disconnect_become_unknown`, B07 |
| S05 | 행동 episode당 1건, 중복 seq 안전 | 통과 | `RealtimeEventTests`, `test_duplicate_and_old_frames_ignored` |
| S06 | 타이핑 등 미학습 행동 오탐 측정 | 미검증 | 보류 로직은 테스트됨. 실제 NG 영상 오탐률 측정은 재학습과 함께 진행 |
| S07 | 구간 합계 = 세션 시간, 겹침 없음 | 통과 | 각 시나리오 `sum(totals) == 경과 시간` |
| S08 | 타인 세션 차단, 동시 활성 세션 방지 | 통과 | `test_only_one_open_session`, `test_other_users_session_is_invisible` |
| S09 | 실시간 원본 프레임 미저장 | 통과 | 프레임은 메모리로만 전달(코드 확인), DB·파일 저장 경로 없음 |
| S10 | 일일/주간 집계·정정 반영 | 통과 | `test_today_counts_only_valid_own_events`, `test_event_correction` |

## 휴식 분류 (STUDY_BREAK_IMPLEMENTATION.md)
| ID | 시나리오 | 상태 |
|---|---|---|
| B01 | 2초 미감지 후 복귀 → 이탈 없음 | 통과 |
| B02 | 10분 후 복귀 → 전체 BREAK | 통과 |
| B03 | 정확히 15분 후 복귀 → BREAK | 통과 |
| B04 | 25분 후 복귀 → 전체 AWAY | 통과 |
| B05·B06 | 걷기·음료 인식 → 횟수만, 시간 상태 변화 없음 | 통과 |
| B07 | 끊김 → pending은 AWAY, 이후 UNKNOWN | 통과 |
| B08 | 수동 휴식 20분 → BREAK 유지 | 통과 |
| B09 | pending 중 종료 → AWAY, 열린 구간 없음 | 통과 |
| B10 | 중복·역순 프레임 | 통과 |
| B11 | AI 모드 시작·재개 → UNKNOWN 후 STUDY | 통과 |
| B12 | 수동 모드 시간 기록 | 통과 |
| — | 실제 카메라 이탈·복귀·끊김 | 미검증 |

## 성능·평가
| ID | 항목 | 상태 | 결과 |
|---|---|---|---|
| E01 | 실시간 처리 FPS·지연 | 통과 | `/predict/frame` p50 52.7ms · p95 60.0ms (pose 24ms, 휴대폰 23ms) → 최대 약 19fps, 6fps 유지 가능 |
| E02 | 독립 사람·각도·NG 데이터 성능 | 미검증 | 사람 단위 교차검증 80%, NG→기타 80%(TRAINING_REPORT.md). 독립 검증 데이터 없음 — 재학습 시 진행 |

Job SUCCESS는 분석 완료이지 행동 정확성 보증이 아니다. 실패 작업은 DB에 남고 오류 메시지에 비밀정보를 넣지 않는다.
