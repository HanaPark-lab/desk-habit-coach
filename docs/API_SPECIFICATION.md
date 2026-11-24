# API 명세 (구현 기준)

## Django / DRF — 세션 로그인 필요, 본인 데이터만 (다른 사용자 것은 404)
| Method | URL | 기능 |
|---|---|---|
| POST | /api/analyses/ | 클립 작업 생성 → 202 + 작업 |
| GET | /api/analyses/ | 내 작업 목록 (20개씩) |
| GET / PATCH / DELETE | /api/analyses/{id}/ | 상세 · 제목/메모만 수정 · 삭제 (PENDING/STARTED는 409) |
| GET | /api/analyses/{id}/status/ | 상태·사람별 결과·기록 여부 (polling) |
| GET | /analyses/cameras/{key}/stream/ | 허용 카메라 MJPEG 중계 (로그인 또는 Celery 토큰) |
| POST | /api/study/sessions/ | 세션 시작 `{"mode": "MANUAL" \| "AI"}` |
| GET | /api/study/sessions/ · /{id}/ | 목록 · 상태·시간 |
| POST | /api/study/sessions/{id}/mode/ | 모드 전환 `{"mode", "roi"?: [x1,y1,x2,y2], "phone_detection"?: bool}` |
| POST | /api/study/sessions/{id}/frames/ | AI 모드 프레임 (multipart `frame` JPEG ≤ 2MB, `seq`) |
| POST | /api/study/sessions/{id}/heartbeat/ | 수동 모드 연결 신호 (30초) |
| POST | /api/study/sessions/{id}/pause/ · resume/ · end/ | 수동 휴식 · 재개 · 종료 |
| GET | /api/study/sessions/{id}/events/ | 세션 행동 기록 |
| GET / PATCH | /api/study/events/ · /{id}/ | 내 행동 기록 · `{"is_valid": false}` 오인식 정정 |
| GET | /api/dashboard/today/ · weekly/ | 상태별 초·행동 횟수(유형·라벨별)·목표 |
| GET | /staff/dashboard/ | 관리자 화면 (is_staff만, 그 외 403) |

**작업 생성** (multipart): `input_type=UPLOAD` + `video_file` 또는 `input_type=IPCAM` + `camera_key`(서버 허용 목록) + `capture_seconds`(5~15). 확장자가 영상이 아니면 작업을 FAILURE(`INVALID_FILE`)로 저장하고 202로 반환한다. 파일 없음·허용되지 않은 카메라·범위 밖 시간은 400.

최종 실행 모델은 자체 학습 4종인 `service`다. 상태 응답의 `model_profile`·`model_version`은 저장된 분석 모델을 나타낸다.

**작업 응답 주요 필드**: `id, status, model_profile, model_version, error_code, error_message, processing_ms, predictions[{track_id, action_label, confidence, window_count, probabilities, event_type, event_score}], record{recorded, event_type, reason}`.

**세션 응답**: `id, status, mode, roi, phone_detection, current_state, current_started_at, seconds{STUDY,BREAK,AWAY,AWAY_PENDING,UNKNOWN}, study_seconds_by_source{AUTO,MANUAL}, distractions, intervals[]` + 평평한 필드:
```json
{"state": "AWAY_PENDING", "study_seconds": 3000, "break_seconds": 0, "away_seconds": 0, "pending_seconds": 120, "unknown_seconds": 0}
```
**프레임 응답**: 세션 응답 + `persons[{index, box, keypoints}]`(index는 프레임 내 순번, 추적 ID 아님), `phones`, `observation`(present/absent/unclear), `ignored`, `action_candidates`, `buffer_steps`, `recorded_event`, `phone_alert`. 수동 모드 409, 종료 세션 409, seq 없음 400, AI 서버 오류 503.

## FastAPI — 내부 전용 (`X-Internal-Token`, `AI_INTERNAL_TOKEN` 설정 시)
| Method | URL | 기능 |
|---|---|---|
| GET | /health | 모델 프로필·버전·클래스·feature 수·버퍼 수 (인증 없음) |
| POST | /predict/video | multipart 영상(≤ MAX_UPLOAD_MB) → 사람별 예측 |
| POST | /predict/frame | 프레임 + `roi`, `stream_key`, `seq`, `detect_phone` → 착석 후보·행동 후보 |
| DELETE | /streams/{key} | 세션 버퍼 삭제 |

영상 결과: `model_profile, model_version, predictions[{track_id, action_label, confidence, window_count, probabilities}], error_code(NO_PERSON/NO_VALID_WINDOW), message, processing_ms`. 422: INVALID_VIDEO, TOO_SHORT(5초 미만), INVALID_FRAME, INVALID_ROI. 413: TOO_LARGE. 401: UNAUTHORIZED.

프레임 결과: `persons, phones, track_count, quality_passed, presence_candidate, action_candidates[{label, probability}], buffer_steps, model_profile, model_version, processing_ms`. DB 쓰기 없음.
