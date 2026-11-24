# API 명세 v2.0
## Django / DRF (인증·소유권 검사)
| Method | URL | 기능 |
|---|---|---|
| POST/GET | /api/jobs/ | 클립 작업 생성·목록 |
| GET/PATCH/DELETE | /api/jobs/{id}/ | 상세·제목/메모 수정·삭제 |
| POST | /api/study/sessions/ | 세션 시작 |
| GET | /api/study/sessions/ | 내 세션 목록 |
| GET | /api/study/sessions/{id}/ | 상태·시간 합계 |
| POST | /api/study/sessions/{id}/frames/ | 실시간 샘플 분석 |
| POST | /api/study/sessions/{id}/pause/ | 수동 휴식 |
| POST | /api/study/sessions/{id}/resume/ | 재개 |
| POST | /api/study/sessions/{id}/end/ | 종료 |
| GET | /api/study/sessions/{id}/events/ | 행동 기록 |
| PATCH | /api/study/events/{id}/ | 오인식 기록 무효화 |
| GET | /api/dashboard/today/ | 일일 시간·행동 집계 |
| GET | /api/dashboard/weekly/ | 주간 집계 |
| GET | /api/admin/summary/ | 관리자 전용 작업 통계 |

Job POST multipart: input_type=upload 또는 ip_webcam, video 또는 허용된 camera_id. 202 + job_id; 잘못된 파일도 Job FAILURE 저장 후 4xx와 ID 반환. PATCH는 제목/메모만. 카메라 주소는 서버 허용 목록 사용.

Frame POST multipart: frame(JPEG), seq(단조 증가 정수). 서버 시간 사용. 세션 ACTIVE만 허용. 중복 seq는 재처리하지 않음, 과거 seq는 무시/409, 요청 과다 429. 응답 예시(가상 수치):
```json
{"session_id":"uuid","seq":42,"state":"STUDY","study_seconds":120,"break_seconds":0,"away_seconds":10,"unknown_seconds":5,"new_events":[{"action_label":"drink_return","event_type":"DRINK","confidence":0.91}]}
```
## FastAPI 내부 전용
| Method | URL | 기능 |
|---|---|---|
| GET | /health | 모델 준비 상태 |
| POST | /predict/video | 공유 볼륨 영상 참조 → 사람별 예측 |
| POST | /predict/frame | 세션별 프레임 → 상태·행동 후보 |
| DELETE | /streams/{key} | 세션 buffer 해제 |

영상 결과: model_version, predictions[{track_id, action_label, confidence, window_count}], processing_ms. 프레임 결과: seq, presence_candidate, quality_passed, track_count, action_candidates[], processing_ms. 입력 경로 정규화, 내부 인증, timeout, 크기 제한. DB 쓰기 없음. 브라우저 세션 ID를 내부 stream key로 매핑한다.
