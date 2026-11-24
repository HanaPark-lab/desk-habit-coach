# Desk Habit Coach 최종 테스트 보고서

검증일 2026-11-24 (Asia/Seoul). 작업 브랜치는 `main`이다. Ubuntu 26.04 x86_64, Python 3.14, Docker Compose 5.6.1, PostgreSQL 17, Redis 7, Chromium Headless 145에서 실행했다. 브라우저 검증은 별도 Compose 프로젝트 `dhc-final-verify`와 로컬 포트 18080, 별도 PostgreSQL·미디어 볼륨 및 테스트 계정으로 수행했다. Django 자동 테스트는 별도의 일회용 테스트 DB를 사용했다. 검증 후 격리 서비스만 중지했고 검증 볼륨은 유지했다.

## 실행 명령과 결과

| 단계 | 명령 또는 실행 범위 | 결과 |
|---|---|---|
| P0 | `python manage.py test analyses.tests.AnalysisApiTests study.tests.PageTests` (로컬 가상환경, 인메모리 SQLite) | 18 PASS, 0 FAIL |
| P0 | `docker compose config --quiet`, `docker compose up -d --build`, `docker compose ps` | 설정 검사, 빌드 및 5개 서비스 기동 PASS. P2에서 기본 프로젝트를 최종 코드로 다시 빌드해 확인 |
| P0/P1 | `docker compose exec -T django python manage.py check`, `docker compose exec -T django python manage.py makemigrations --check --dry-run` | 설정 오류 0개, 마이그레이션 변경 없음 |
| P1 | `python manage.py test study.tests.RealtimeEventTests study.tests.BreakRuleTests` (로컬 인메모리 SQLite) | 수정 후 16 PASS, 0 FAIL |
| P1 | `docker compose exec -T django python manage.py test` (격리 프로젝트) | 84 PASS, 0 FAIL |
| P1 | `docker compose exec -T fastapi python -m pytest -q` (격리 프로젝트) | 17 PASS, 0 FAIL. Starlette TestClient의 httpx 관련 사용 중단 예고 경고 1건 |
| P1 | 격리 프로젝트 `docker compose restart` 및 `docker compose up -d --wait` | 동일한 SUCCESS 작업, 두 예측 행 및 원본 MP4 재확인 |
| P2 | Chromium에서 실제 페이지와 MP4 처리 흐름 검증, 화면 6장 캡처, README 링크와 PNG 확인 | PASS |
| P2 | `git diff --check` | PASS |

전체 자동 테스트 최종 결과는 **101 PASS, 0 FAIL**이다. 단계별 선별 테스트는 전체 합계에 중복 산입하지 않았다. 로컬 FastAPI 실행이 응답을 반환하지 않아 중단했고, 컨테이너에서 전체 스위트를 완료했다. 첫 행동 회귀 테스트에서 손 흔들기 직후의 걷기가 누락됨을 재현했다. episode와 60초 중복 판정에 모델 라벨을 사용하도록 바꾼 뒤 같은 행동의 반복 방지와 다른 행동의 연속 기록을 확인했다. 시간 엔진은 기존 구현을 유지했다.

## 필수 테스트

| ID | 결과 | 증거 |
|---|---|---|
| T01 자체 학습 모델 | PASS | FastAPI가 `rf-2026-11-24-other`를 로드했고 `/health`에서 `service`, 정확한 4종 클래스 및 1140차원을 확인했다. 자동 테스트로 JSON feature 순서, 30 step, 38 feature, 6fps를 검사했다. 학습과 추론의 공통 `track_people`·`step_features` 및 시퀀스 코드를 대조했다. 사용자 확인에 따라 원 교과의 제공 모델 6종 요구를 자체 모델 4종으로 대체했다. |
| T02 MP4 분석·저장 | PASS | Chromium에서 테스트 MP4를 업로드했고 Django→Redis→Celery→FastAPI→PostgreSQL 흐름을 거쳐 결과가 표시됐다. |
| T03 실제 IP Webcam | NOT RUN | 가짜 입력으로 MJPEG 중계, 수집 길이, 연결 실패를 자동 검증했다. 실제 IP Webcam 장치는 연결할 수 없었다. |
| T04 다중 인물 | PASS | 실제 MP4 분석 결과에서 Track ID 1과 2를 확인했다. 다중 인물의 개인 행동 기록 보류는 자동 테스트로 확인했다. |
| T05 비동기 작업 ID | PASS | 브라우저에서 HTTP 202 및 작업 ID를 먼저 받고 후속 상태 조회에서 완료 결과를 확인했다. |
| T06 상태·예측 저장 | PASS | PostgreSQL에 SUCCESS 및 각 Track ID의 예측 행이 저장됐다. |
| T07 사용자 격리·CRUD | PASS | 다른 사용자의 상세·상태·수정·삭제 차단, 제목·메모 수정, 연결 데이터 삭제, 본인 최근 7일 이력 노출을 자동 검증했다. |
| T08 관리자 목록·차트 | PASS | 관리자 전용 접근 및 DB 기반 집계를 테스트하고 실제 차트를 캡처했다. |
| T09 오류 처리 | PASS | 유효하지 않은 파일·영상, 큐/AI/저장 오류, 카메라 수집 오류 경로를 자동 검증했다. 실제 물리 카메라 수집 실패 재현은 미검증이다. |
| T10 재시작 후 영속성 | PASS | 격리된 프로젝트의 5개 서비스를 재시작한 뒤 동일 작업 ID, SUCCESS, 두 예측 행, 원본 MP4 존재를 확인했다. |

## 집중 모드와 브라우저

| 항목 | 결과 | 증거 |
|---|---|---|
| 시간 경계·전환 | PASS | AI 시작 UNKNOWN, 안정 감지 3초, 부재 5초, 복귀 안정 확인 3초, 첫 복귀 관측이 정확히 15분이면 BREAK, 15분 1초면 AWAY. 10분·25분 구간, 미확정 이탈 중 종료, 연결 끊김·재연결, 수동 전환·휴식, 중복·역순 프레임, 자정 경계 검증. |
| 행동과 시간 상태 | PASS | 음료·움직임 횟수가 시간 상태를 변경하지 않고, 손 흔들기 직후 걷기가 별도로 기록됨을 검증했다. `other`와 낮은 모델 점수는 보류됐다. |
| 30 step 버퍼 | PASS | 30 step에서 첫 예측, 이후 6 step마다 예측, 2 step을 넘는 입력 공백에서 초기화, 불명확 대상 초기화를 검증했다. |
| 가상 카메라 처리율·수동 전환 | PASS | Chromium에 640×480 고정 1인 클립을 입력했다. 약 13.87초 동안 정상 응답 84개(완료 응답 간 평균 5.99fps), 최대 응답 간격 334ms, HTTP 오류 0건, 버퍼 최대 30 step과 예측 응답 8개를 관측했다. 카메라 끄기 후 수동 모드 진입과 종료를 확인했다. 실제 카메라·네트워크의 지속 6fps는 미검증이다. |
| 분석·기록 화면 | PASS | 분석 화면에서 이력 제거, IP Webcam 탭의 미리보기 영역, `?job=` 유지와 새로고침 후 결과 복원, 완료 후 4.5초간 재탐색 없음, 기록 화면의 상세 링크를 확인했다. |
| 집중 모드 레이아웃 | PASS | 375px에서 1열, 1280px에서 2열, 카메라 패널과 같은 너비, 문서 가로 넘침 없음, 어두운 패널에서 밝은 옵션 글자를 확인했다. |
| 물리 카메라 장시간 시나리오 | NOT RUN | 실제 웹캠 연결, 브라우저 권한 변경, 실제 동작과 장시간 이탈·복귀는 실행하지 않았다. |
| 독립 사용자·각도·NG 영상 | NOT RUN | 타이핑·마우스·턱 괴기·얼굴 만지기의 오탐률을 측정할 독립 검증 영상을 사용하지 못했다. 학습 보고서의 80%는 3명 사람 단위 교차검증 결과다. |

## 남은 수동 검증

1. 브라우저에서 실제 카메라를 허용하고 집중 모드를 시작한다. 한 사람이 3초간 감지되면 공부 시간 누적을 확인한다. 음료·손 흔들기·걷기는 조건을 충족했을 때 횟수가 추가되고 시간 상태는 유지되어야 한다.
2. 10분 자리 이탈 후 돌아오고 복귀를 3초간 유지한다. 비운 전체 시간이 휴식으로 표시되어야 한다. 15분을 넘겨 반복하면 전체가 장기 자리 비움으로 표시되어야 한다.
3. 카메라 권한을 해제하거나 브라우저를 닫은 뒤 기록을 확인한다. 연결이 끊긴 시점 이후의 구간은 확인 불가로 정산되어야 한다. 카메라 끄기 버튼을 사용할 때는 수동 타이머로 전환되어야 한다.
4. 같은 네트워크에서 허용된 IP Webcam을 열어 미리보기와 5~15초 클립 분석을 확인한다.
5. 학습에 포함되지 않은 사람과 촬영 각도에서 행동과 NG 동작을 실측하고 오탐·누락을 기록한다.

## 변경 파일

- 분석·기록 화면과 검증: `backend/analyses/page_views.py`, `backend/analyses/tests.py`, `backend/dashboard/views.py`, `backend/static/js/analyses.js`, `backend/templates/analyses/list.html`, `backend/templates/dashboard/reports.html`
- 집중 모드 안내와 행동 검증: `backend/templates/study/session.html`, `backend/static/css/app.css`, `backend/study/services/event_service.py`, `backend/study/tests.py`
- 모델 검증: `ai_service/tests/test_api.py`, `.env.example`
- 제출 문서와 화면: `README.md`, `docs/README.md`, `docs/AI_PIPELINE.md`, `docs/API_SPECIFICATION.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_PLAN.md`, `docs/ERD.md`, `docs/TEST_CASES.md`, `docs/UI_UX.md`, 이 보고서 및 `docs/screenshots/` PNG 6장

## 활동 기록 대시보드 후속 검증 (2026-11-24)

기본 7일은 일별, 4주는 오늘을 포함한 28일의 7일 단위 네 구간이다. 음료 목표선은 기존 `DAILY_GOALS["DRINK"]` 기준 일 8회, 주 56회로 확인했다. 활동 기록 화면은 로그인 사용자의 실제 ORM 집계만 사용한다. 재현용 기록은 격리 검증 프로젝트의 테스트 계정에만 넣었다.

| 검증 | 결과 | 증거 |
|---|---|---|
| Django PostgreSQL 전체 회귀 | PASS | 격리 Compose에서 `docker compose exec -T django python manage.py test`. 88개 통과, 실패 0개. 대시보드 신규 4개 포함. |
| ORM 집계 | PASS | 7일·28일 양 끝 날짜, 자정에 걸친 공부 시간, AI·수동 분리, 휴식·자리 비움·확인 불가, 유효한 행동과 소유자 범위를 검증했다. |
| Chart.js 및 기간 전환 | PASS | Chromium 145에서 시간 누적 막대, 도넛, 음료 막대·목표선, 손 흔들기·걷기 그룹 막대를 확인했다. 7일과 4주의 구간 수와 음료 목표선 값을 검증했다. |
| 행동 정정과 분석 상세 | PASS | 브라우저에서 오인식 정정·취소 시 선택한 기간을 유지하고 집계가 갱신됐다. 접힌 분석 이력을 열고 상세 화면의 수정·삭제 컨트롤에 접근했다. CRUD와 사용자 격리는 Django 테스트에서도 확인했다. |
| 반응형·빈 상태 | PASS | 1280px·375px에서 확인했다. 375px에서 분석 표를 펼친 상태로도 문서에 가로 넘침이 없었다. 빈 계정과 Chart.js CDN 차단 상황의 안내를 확인했다. |
| 스키마와 변경 검사 | PASS | `makemigrations --check --dry-run`과 `git diff --check` 통과. 모델 파일 및 DB 스키마 변경 없음. |

변경 파일은 `backend/dashboard/views.py`, `backend/dashboard/tests.py`, `backend/templates/dashboard/reports.html`, `backend/static/js/reports.js`, `backend/static/css/app.css`, `docs/UI_UX.md` 및 이 보고서다.

## 오늘 화면과 집중 모드 진입 후속 검증 (2026-11-24)

| 검증 | 결과 | 증거 |
|---|---|---|
| Django PostgreSQL 전체 회귀 | PASS | 격리 Compose에서 `docker compose exec -T django python manage.py test` 실행. 91개 통과, 실패 0개. 오늘 화면·집중 모드 진입 테스트 3개 포함. |
| 공부 시작·이어하기 | PASS | Chromium에서 오늘 버튼이 기존 생성 API에 `MANUAL`을 보내고 201 응답 뒤 집중 모드를 열었다. 활성·휴식 세션은 동일 ID를 열었으며 휴식 진입 시 자동 재개 요청이 없었다. 이전 상태를 표시한 다른 탭에서 409가 반환돼도 열린 세션으로 이동했고 DB에 중복 세션이 없었다. |
| 수동 기본값·카메라 선택 | PASS | 오늘 화면에서 시작하거나 집중 모드에서 직접 시작할 때 카메라 권한 요청이 없었다. 가상 카메라로 사용자가 카메라를 켠 뒤 AI 모드, 끈 뒤 수동 타이머로 전환되는 것을 확인했다. 실제 카메라는 이번 변경에서 미검증이다. |
| 세션 종료·오류 | PASS | 종료 실패 응답에서 집중 모드에 남아 오류를 표시하고 다시 시도할 수 있었다. 정상 종료 후 오늘 화면으로 돌아와 DB에 저장된 공부 시간이 표시됐다. |
| 집계·반응형·기록 링크 | PASS | 저장된 공부·휴식·행동 기록과 달성률, 월~일 그래프, 빈 상태를 검증했다. Chromium 1280px·375px에서 확인했으며 모바일에서 주간 차트의 가로 넘침 없이 시작 버튼이 카드 너비를 사용했다. 기록 링크는 `/reports/`로 이동했다. |
| 검사 | PASS | `makemigrations --check --dry-run`, 두 JS 파일의 `node --check`, `git diff --check` 통과. |

테스트 계정과 실제 API로 만든 테스트 세션은 격리 검증 DB만 사용했다. 기존 AI 모델, DB 스키마 및 사용자 기록을 유지했다.

## 관리자 사용자 이용 현황 후속 검증 (2026-11-24)

| 검증 | 결과 | 증거 |
|---|---|---|
| PostgreSQL 마이그레이션 | PASS | 격리 Docker에서 `dashboard.0001_initial` 적용. 기존 계정이 남아 있고 신규 활동 테이블은 최초 브라우저 요청 전 비어 있음을 확인했다. |
| Django 회귀 테스트 | PASS | 격리 PostgreSQL에서 `python manage.py test` 실행. 전체 94개 통과, 실패 0개. 관리자 사용 현황 테스트 3개를 포함한다. |
| 집계 규칙 | PASS | Django 설정을 UTC로 두고도 서울 자정에 날짜를 분리했다. 같은 사용자의 반복 로그인·접속이 중복 집계되지 않았고, 접속이 수집되지 않은 기존 계정의 `last_login`은 최근 접속 시각으로 표시되지 않았다. |
| 실제 이용·사용자 상세 | PASS | 자정에 걸친 공부 시간을 분리해 오늘 AI·수동 시간을 각각 집계했다. 분석 요청과 공부를 모두 한 사용자도 한 번만 집계했고, 최근 가입·오늘 접속 목록과 분석 작업 수를 확인했다. |
| 권한·브라우저 | PASS | Chromium에서 비관리자 403, 실제 가입→재로그인→반복 접속→수동 세션 흐름의 지표 변화와 서울 현지 시각을 확인했다. 사용자 추이와 기존 분석 차트가 함께 표시됐고, 1280px·375px 화면에서 검증했다. |
| 최종 검사 | PASS | `makemigrations --check --dry-run`, 관리자 JS 문법 검사, `git diff --check` 통과. |

로그인과 접속을 사용자당 서울 날짜 한 행으로 기록한다. 기존 DB에서 가입·공부·분석은 집계했고, 과거 접속 시각과 날짜별 로그인 여부는 소급 생성하지 않았다. 실제 이용 기준은 집계 가능한 공부 시간 1초 이상 또는 분석 요청 1건 이상이다.

## 행동 표시명 통일 후속 검증 (2026-11-24)

- 격리 PostgreSQL에서 Django 전체 94개 통과. 최신 표시명 단언을 포함한 기록·분석 선별 테스트 19개도 통과했다.
- Chromium에서 오늘, 집중 모드 알림, 분석 결과, 기록 목록·그래프 범례, 관리자 대시보드의 새 명칭을 확인했다. 집중 모드 알림은 가상 카메라와 테스트 프레임 응답으로 UI만 검증했다. README Figure 04를 Mermaid로 렌더링했다.
- `wave`와 `walk_turn_walk`의 최종 학습 원본에서 각 6개, 총 12개 표본을 확인했다. 촬영 전 가이드와 실제 원본 표본의 `wave` 자세 차이를 [학습 보고서](TRAINING_REPORT.md#서비스-표시명과-학습-동작)에 기록했다.
- Joblib과 Feature JSON의 SHA-256은 작업 전후 동일했다. 마이그레이션 검사에서 변경이 없었으며, 모델 클래스와 기존 DB 저장값, 행동 기록 및 시간 판정 로직을 유지했다.
