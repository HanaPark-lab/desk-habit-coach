# Desk Habit Coach — 최종 구현 및 검증 지시서

## 1. 목표 및 확정 범위

기존 프로젝트를 유지하면서 UI를 정리하고 실제 작동을 검증하여 교과 10 제출 및 포트폴리오 준비를 완료한다. 새로운 기능이나 모델 재학습은 추가하지 않는다. 교과용 6종 모델은 사용하지 않아도 된다는 사용자 확인에 따라 최종 필수 범위에서 제외한다.

- 최종 모델: 자체 학습 RF 4종 (`drink_return`, `wave`, `walk_turn_walk`, `other`). 기존 가중치, 38개 feature, 30 step, 6fps 입력 및 정규화 유지.
- 음수는 횟수만 기록한다. 손 흔들기는 스트레칭 대용 활동, 걷기는 움직임 기록이다. 두 행동만으로 휴식 시간을 확정하지 않는다.
- 기존 Django/DRF, FastAPI, Celery, Redis, PostgreSQL, Docker Compose 구조 유지.
- 실시간 분석과 MP4/IP Webcam 클립 분석 유지. 휴대폰 감지는 선택 기능이며 공부 시간을 차감하지 않는다.

## 2. Codex 작업 원칙

1. 저장소 루트에서 `git status --short`, `git branch --show-current` 확인. 사용자 변경 사항을 덮어쓰거나 초기화하지 않는다.
2. 아래 파일과 실제 URL, 모델 설정, 테스트 구성을 먼저 읽는다. 파일명이 달라졌다면 현재 코드 기준으로 수정한다.
3. 작은 단위로 수정하고 관련 테스트를 실행한다. 기존 API, DB 데이터, 인증, 권한을 유지한다. 불필요한 마이그레이션 금지.
4. 실제 실행 결과와 미검증 항목을 구분한다. 카메라 권한, 외부 장치 등 사용자 조작이 필요한 항목은 수동 검증으로 남긴다.
5. 자동 커밋·푸시, DB 삭제, `docker compose down -v`, 비밀정보 공개는 하지 않는다. 오류가 있으면 원인을 보고하고 최소 수정한다.

## 3. P0 — 분석 화면 정리

### 대상 파일
- `backend/templates/analyses/list.html`
- `backend/static/js/analyses.js`
- `backend/analyses/page_views.py`
- `backend/templates/dashboard/reports.html`
- `backend/dashboard/views.py`

### 구현
- [ ] `/analyses/`의 `recent-title` 섹션(최근 분석 이력 표) 전체 제거. 영상 입력, IP Webcam 미리보기, 분석 상태, 분석 결과는 유지.
- [ ] `analyses.js`의 `poll()`에서 `data-job-row` 존재 여부에 따라 `location.replace()`를 호출하는 분기 제거. 이력을 삭제하면 반복 새로고침이 발생할 수 있다.
- [ ] `track()`의 `?job=` 유지 및 새로고침 후 결과 복원 유지. 완료 시 `afterDone` 호출과 IP Webcam 미리보기 유지. 필요하면 완료된 작업 상세 링크 제공.
- [ ] 분석 페이지에서 더 이상 쓰지 않는 최근 작업 조회 쿼리만 제거. `page_config` 등 필수 context 유지.
- [ ] `/reports/`에 별도의 분석 이력 표 추가: 일시, 입력 방식, 제목, 상태, 예측 행동, 상세 링크. 현재 사용자의 작업만 조회하고 최근 7일 또는 페이지네이션으로 제한. 실패 및 기록되지 않은 작업도 포함. 기존 AI 행동 기록 및 정정 기능 유지.
- [ ] 상세 화면의 제목·메모 수정 및 삭제 유지. 삭제 후 기록 페이지로 이동하도록 검토.

완료 기준: 분석 화면에 최근 이력 없음, 분석 완료 후 반복 새로고침 없음, URL 복원 정상, 기록 화면에서 본인 분석 조회 가능, 타 사용자 작업 접근 불가.

## 4. P0 — 집중 모드 안내 UI

대상: `backend/templates/study/session.html`(실제 템플릿 경로 확인), `backend/static/css/app.css`.

- [ ] 하단의 좁은 장문 안내를 기존 콘텐츠 컨테이너 전체 너비의 안내 카드로 변경한다. 기존 공통 `p` 스타일의 max-width 제한이 원인인지 확인하고 안내 카드 내부에만 override한다.
- [ ] 제목: 집중 모드 이용 안내. 데스크톱 2열, 모바일 1열. 기존 초록/아이보리 테마와 카드 여백 유지.
- [ ] 안내 항목: 공부 시간 측정(3초 안정 감지), 휴식 및 자리 비움(5초 미감지, 15분 이내 복귀 시 휴식), 자동 행동 기록(음료·손 흔들기·걷기), 개인정보(실시간 영상 미저장, 결과만 저장).
- [ ] 하단 보조 문구: AI 시간은 실제 집중도가 아닌 사람 감지 기반 추정이며, 가림·다중 인물·연결 끊김은 확인 불가로 처리. 카메라를 끄면 수동 타이머로 전환. 수동 휴식은 시간과 무관하게 휴식. 휴대폰 감지는 선택이며 시간 차감 없음.
- [ ] 기존 영상 분석 링크 유지. 카메라 패널의 옵션 글자 대비 개선. 기존 JS가 사용하는 ID, 버튼, 상태 요소는 유지.

CSS 예시(기존 변수 확인 후 적용):
```css
.focus-guide { width: 100%; max-width: none; box-sizing: border-box; margin-top: 16px; }
.focus-guide-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.focus-guide p { max-width: none; overflow-wrap: anywhere; }
@media (max-width: 760px) { .focus-guide-grid { grid-template-columns: 1fr; } }
```

완료 기준: 안내 카드가 타이머/카메라 영역과 동일한 콘텐츠 너비를 사용하고 375px 및 데스크톱에서 가로 스크롤이나 잘림이 없다.

## 5. P0 — 모델 및 문서 정합성

- [ ] 기본 모델 프로필이 자체 4종 모델인지 `.env.example`, Compose, 모델 로더, `/health` 확인. 실제 `.env` 비밀정보는 출력하지 않는다.
- [ ] 교과 6종 파일 누락을 실패 조건으로 두지 않는다. 기존 선택 프로필은 호환용으로 남겨도 되지만 실행 필수 조건에서 제외한다.
- [ ] T01을 자체 모델 파일 로딩, 정확한 클래스 집합, 1140차원 feature 순서, 30 step, 6fps, 학습/추론 전처리 일치 검증으로 갱신한다. 원 교과 요구와 사용자 확인에 따른 변경을 문서에 명시한다.
- [ ] `docs/TEST_CASES.md`, `docs/UI_UX.md`, `docs/DEVELOPMENT_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/ERD.md`, `docs/API_SPECIFICATION.md`, `docs/AI_PIPELINE.md`를 실제 구현과 대조하고 불일치만 수정한다.

## 6. P1 — 시간 및 행동 검증

기존 시간 엔진을 재작성하지 말고 다음 기준과 실제 구현을 비교한다. 불일치가 재현되는 경우만 최소 수정한다.

| 조건 | 기대 결과 |
|---|---|
| AI 모드 시작 | UNKNOWN, 시간 누적 보류 |
| 한 사람 3초 안정 감지 | STUDY |
| 5초 이상 연속 미감지 | AWAY_PENDING, 공부 시간 제외 |
| 15분 이내 복귀 확인 | 전체 이탈 구간 BREAK |
| 15분 초과 이탈 | 전체 이탈 구간 AWAY |
| 수동 일시정지 | BREAK |
| 연결 끊김/다중 인물/가림 | UNKNOWN, 공부 시간 제외 |
| 음료 감지 | 음수 +1, 시간 상태 변경 없음 |
| 손 흔들기/걷기 | 활동 +1, 시간 상태 변경 없음 |
| other/낮은 점수 | 기록 안 함 |

- [ ] 5초, 3초, 15분 경계값 및 복귀 확인 지연 테스트. 정확히 15분은 휴식 기준으로 검증하며 복귀 시각 정의를 일관되게 적용한다.
- [ ] 세션 종료 시 미확정 이탈 구간 처리, 카메라 연결 끊김, 재연결, 수동 전환, 중복 프레임, 날짜 경계 검증.
- [ ] 동일 행동 연속 프레임의 중복 이벤트 방지, 서로 다른 행동의 누락 여부 확인.
- [ ] 실시간 6fps 실제 처리율과 30 step 버퍼 확인. 프레임 누락 시 정상 6fps라고 가정하지 않는다.
- [ ] 타이핑, 마우스, 턱 괴기, 얼굴 만지기 등 NG 오탐과 다른 사용자·각도 검증. 기존 학습 보고서의 80%는 3명 교차검증 결과이며 독립 테스트 정확도가 아니다.

## 7. P1 — 통합 테스트

실제 저장소의 README/Compose/테스트 설정을 먼저 확인하고 아래 명령은 서비스명 및 경로에 맞게 실행한다.

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
# 실제 서비스명 확인 후 실행
docker compose exec django python manage.py check
docker compose exec django python manage.py makemigrations --check --dry-run
docker compose exec django python manage.py test
docker compose exec fastapi python -m pytest -q
```

테스트 도구가 컨테이너에 없다면 기존 개발 환경에서 실행한다. 기존 DB와 분리된 테스트 DB 사용. 실패 로그를 확인하고 수정 후 재실행한다.

- [ ] T01 자체 4종 모델 검증
- [ ] T02 MP4 업로드 및 분석 결과 저장
- [ ] T03 실제 IP Webcam 수집 및 분석
- [ ] T04 다중 인물 Track ID별 결과
- [ ] T05 비동기 요청 즉시 작업 ID 반환
- [ ] T06 작업 상태 및 예측 DB 저장
- [ ] T07 사용자 A/B 권한 격리 및 CRUD
- [ ] T08 관리자 목록 및 차트
- [ ] T09 잘못된 영상/카메라 수집 실패 시 오류 안내 및 FAILURE 저장
- [ ] T10 Docker 재시작 후 DB 데이터 유지(볼륨 삭제 금지)
- [ ] 집중 모드 자동 테스트 및 UI 회귀 테스트
- [ ] 실제 카메라로 10분 이탈 후 복귀, 15분 초과 이탈, 카메라 권한 해제, 브라우저 종료, 음수/움직임 기록 확인

## 8. P2 — 제출 준비

- [ ] README: 목적, 기능, 모델 4종, 설치/실행, 환경변수 예시, 아키텍처, 화면, 테스트 결과, 알려진 한계.
- [ ] 실제 UI 캡처: 오늘, 집중 모드, 분석, 기록, 관리자.
- [ ] 시연 순서: 세션 시작 → 음수/움직임 → 자리 이탈/복귀 → 기록 확인 → MP4 분석 → 관리자 통계.
- [ ] 개인정보, 영상 저장 정책(실시간과 업로드 구분), 모델 오인식 가능성 명시.
- [ ] `git diff --check`, 변경 파일 목록 및 테스트 결과 확인.

## 9. 최종 보고 형식

`docs/FINAL_TEST_REPORT.md`에 날짜, 실행 환경, 명령, 성공/실패 수, 테스트별 PASS/FAIL/NOT RUN, 실제 카메라 검증 여부, 수정 파일, 남은 이슈를 기록한다. 체크박스는 증거가 확보된 항목만 완료 처리한다. 수동 검증이 남아 있으면 사용자에게 필요한 조작과 기대 결과를 안내한다. 테스트 결과를 꾸며내지 않는다.

최종 완료 조건: UI 요구 충족, 자체 4종 모델 정상 로딩, 필수 기능 및 자동 테스트 통과, Docker 실행 확인, 수동 검증 결과 또는 미검증 사유 명시, 문서 최신화. 범위 밖 기능은 추가하지 않는다.
