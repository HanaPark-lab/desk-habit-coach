# 테스트 결과 (2026-11-24)

최종 실행 환경, 명령과 미검증 범위는 [최종 테스트 보고서](FINAL_TEST_REPORT.md)를 참조한다. Django 84개와 FastAPI 17개가 통과했다.

상태 **통과**는 자동 테스트 또는 직접 실행으로 확인한 항목, **부분**은 일부를 확인한 항목, **미검증**은 실행하지 않은 항목이다.

## 교과 필수
| ID | 통과 기준 | 상태 | 근거 |
|---|---|---|---|
| T01 | 자체 학습 4종·1140 feature 순서·30 step·6fps·학습/추론 전처리 일치 | 통과 | `test_service_model_contract`, `test_feature_spec`, `test_health`, 공통 전처리 경로 확인. 원 교과의 제공 6종 요구는 사용자 확인에 따라 자체 학습 4종으로 대체 |
| T02 | MP4 업로드 후 사람별 결과 | 통과 | `test_people_video`, `AnalyzeTaskTests`, 격리 Docker E2E(업로드→Celery→FastAPI→DB) |
| T03 | IP Webcam 짧은 클립 수집·분석 | 부분 | 가짜 카메라로 수집·중계 테스트 통과. 최종 검증에서 실제 IP Webcam 미실행 |
| T04 | 다중 인물 Track ID별 결과 | 통과 | `test_people_video`(bus.jpg 여러 명), 개인 기록 보류 `test_multiple_people_hold_personal_record` |
| T05 | 비동기 작업 ID 즉시 반환 | 통과 | `test_upload_creates_pending_job_and_queues_it` (202) |
| T06 | PostgreSQL 작업·예측 영구 저장 | 통과 | 격리 Docker E2E 작업 SUCCESS 및 2명 예측 저장 확인 |
| T07 | 사용자 A/B 격리 | 통과 | `test_other_users_job_is_invisible`, `test_other_users_session_is_invisible` |
| T08 | 관리자 목록·상태 차트 | 통과 | `test_staff_dashboard_uses_real_db_counts` |
| T09 | 실패 메시지·FAILURE 저장 | 통과 | 잘못된 파일, AI 다운, 큐 다운, 결과 저장 오류, 중단 작업 정산 테스트 |
| T10 | Docker 재시작 후 DB 유지 | 통과 | 격리 Compose 재시작 후 동일 SUCCESS 작업, 두 예측 행, 원본 MP4 확인 |

## 공부 세션·행동
| ID | 통과 기준 | 상태 | 근거 |
|---|---|---|---|
| S01 | 세션 시작·종료, 카메라 해제 | 부분 | API·엔진 통과. 실제 카메라 권한 해제 및 브라우저 종료는 미검증 |
| S02 | 자리 비움·복귀 자동 전이 | 통과 | `AiModeTests`, `BreakRuleTests` |
| S03 | 수동 휴식 우선, 재개 시 UNKNOWN | 통과 | `test_break_is_manual_and_resume_enters_unknown`, B08 |
| S04 | 끊김·가림은 UNKNOWN, 과대 누적 방지 | 통과 | `test_unclear_frames_and_disconnect_become_unknown`, B07 |
| S05 | 행동 라벨별 episode당 1건, 중복 seq 안전 | 통과 | `RealtimeEventTests`, `test_duplicate_and_old_frames_ignored` |
| S06 | 타이핑 등 미학습 행동 오탐 측정 | 미검증 | 보류 로직은 테스트됨. 독립 NG 영상 오탐률은 미측정 |
| S07 | 구간 합계 = 세션 시간, 겹침 없음 | 통과 | 각 시나리오 `sum(totals) == 경과 시간` |
| S08 | 타인 세션 차단, 동시 활성 세션 방지 | 통과 | `test_only_one_open_session`, `test_other_users_session_is_invisible` |
| S09 | 실시간 원본 프레임 미저장 | 통과 | 프레임은 메모리로만 전달(코드 확인), DB·파일 저장 경로 없음 |
| S10 | 일일/주간 집계·정정 반영 | 통과 | `test_today_counts_only_valid_own_events`, `test_event_correction` |

## 휴식 분류
| ID | 시나리오 | 상태 |
|---|---|---|
| B01 | 2초 미감지 후 복귀 → 이탈 없음 | 통과 |
| B02 | 10분 후 복귀 → 전체 BREAK | 통과 |
| B03 | 정확히 15분 후 복귀 → BREAK | 통과 |
| B04 | 15분 1초 또는 25분 후 복귀 → 전체 AWAY | 통과 |
| B05·B06 | 잠깐 자리 비움·음료 섭취 인식 → 횟수만, 시간 상태 변화 없음 | 통과 |
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
| E01 | 실시간 처리율·버퍼 | 부분 | 가상 카메라로 정상 응답 84개, 약 13.87초, 평균 5.99fps, 30 step 도달. 실제 카메라 처리율 미측정 |
| E02 | 독립 사람·각도·NG 데이터 성능 | 미검증 | 학습에 포함된 3명의 사람 단위 교차검증 80%. 독립 검증 영상 미실행 |

Job SUCCESS는 분석 완료이지 행동 정확성 보증이 아니다. 실패 작업은 DB에 남고 오류 메시지에 비밀정보를 넣지 않는다.
