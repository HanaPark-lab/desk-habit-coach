# 학습 결과 보고서

- 생성: `training/train_rf.py` · 2026-11-24 · 모델 `rf-2026-11-24-other`
- 입력: 30 Step × 38 Feature = 1140 · 6fps (5초 Window, 1초 간격) · 쉬는 구간 Window 제외
- 모델: RandomForest(n_estimators=300, min_samples_leaf=2, class_weight=balanced)
- 클래스: `drink_return`, `other`, `walk_turn_walk`, `wave` (`other` = X### 폴더의 NG 행동 전체)

## 데이터

| 폴더 | 라벨 | 영상 | Window | 사람 | top / bottom |
|---|---|---:|---:|---|---|
| A001_drink_return | `drink_return` | 21 | 102 | P01, P02, P03 | 12 / 9 |
| A002_wave | `wave` | 18 | 86 | P01, P02, P03 | 9 / 9 |
| A003_walk_turn_walk | `walk_turn_walk` | 16 | 25 | P01, P02, P03 | 9 / 7 |
| X001_sit_still | `other` | 3 | 12 | P01 | 3 / 0 |
| X002_phone_call | `other` | 3 | 14 | P01 | 3 / 0 |
| X003_hand_raise | `other` | 2 | 2 | P01 | 2 / 0 |
| X004_scratch_head | `other` | 3 | 12 | P01 | 3 / 0 |
| X005_touch_hair | `other` | 4 | 15 | P01 | 4 / 0 |

Window가 없어 제외된 영상 (사람이 5초 이상 잡히지 않음): `A003_walk_turn_walk/P01_bottom_R02.mp4`, `A003_walk_turn_walk/P01_bottom_R03.mp4`, `A003_walk_turn_walk/P02_bottom_R01.mp4`, `X003_hand_raise/P01_top_R02.mp4`

## 교차검증

### 처음 보는 사람 (동작 영상)

한 사람의 영상을 전부 빼고 학습한 뒤 그 사람을 평가한다.

| 평가한 사람 | 영상 | 정답 | 정확도 |
|---|---:|---:|---:|
| P01 | 17 | 17 | 100.0% |
| P02 | 18 | 10 | 55.6% |
| P03 | 20 | 17 | 85.0% |
| **전체** | 55 | 44 | **80.0%** |

카메라 각도별: top 76.7% · bottom 84.0%

### 처음 보는 기타 행동 (NG 영상)

NG 행동 하나를 통째로 빼고 학습한 뒤, 그 행동이 `other`로 걸러지는지 평가한다.

| 뺀 행동 | 영상 | `other`로 걸러짐 |
|---|---:|---:|
| X001_sit_still | 3 | 3 |
| X002_phone_call | 3 | 3 |
| X003_hand_raise | 2 | 1 |
| X004_scratch_head | 3 | 3 |
| X005_touch_hair | 4 | 2 |
| **전체** | 15 | **12 (80.0%)** |

### 혼동행렬 (행 = 실제, 열 = 예측, 교차검증)

| 실제 \ 예측 | `drink_return` | `other` | `walk_turn_walk` | `wave` |
|---|---:|---:|---:|---:|
| `drink_return` | 16 | 1 | 0 | 4 |
| `other` | 2 | 12 | 1 | 0 |
| `walk_turn_walk` | 0 | 2 | 11 | 3 |
| `wave` | 1 | 0 | 0 | 17 |

틀린 영상: `A001_drink_return/P02_top_R01.mp4` → `wave`, `A001_drink_return/P02_top_R02.mp4` → `wave`, `A001_drink_return/P02_top_R03.mp4` → `wave`, `A001_drink_return/P02_top_R04.mp4` → `wave`, `A001_drink_return/P03_top_R02.mp4` → `other`, `A002_wave/P02_bottom_R02.mp4` → `drink_return`, `A003_walk_turn_walk/P02_bottom_R02.mp4` → `wave`, `A003_walk_turn_walk/P02_top_R01.mp4` → `wave`, `A003_walk_turn_walk/P02_top_R02.mp4` → `wave`, `A003_walk_turn_walk/P03_bottom_R01.mp4` → `other`, `A003_walk_turn_walk/P03_bottom_R03.mp4` → `other`, `X003_hand_raise/P01_top_R03.mp4` → `drink_return`, `X005_touch_hair/P01_top_R02.mp4` → `drink_return`, `X005_touch_hair/P01_top_R04.mp4` → `walk_turn_walk`

## 습관 기준값

처음 본 NG 영상이 각 습관으로 나온 최고 점수보다 조금 높게 잡는다 (최소 0.5).
'통과'는 처음 보는 사람의 동작 영상 중 그 기준에서 제대로 인정되는 수, 'NG 잘못 인정'은 기준 0.5일 때 습관으로 잘못 인정됐을 NG 영상 수다.

| 습관 | NG 최고 점수 | 제안 기준값 | 통과 | 기준 0.5일 때 NG 잘못 인정 |
|---|---:|---:|---:|---:|
| DRINK | 0.51 | **0.56** | 13/21 | 1 |
| MOVEMENT | 0.59 | **0.64** | 21/34 | 2 |

`.env`에 반영:

```dotenv
EVENT_THRESHOLD_DRINK=0.56
EVENT_THRESHOLD_MOVEMENT=0.64
```

### NG 영상별 결과 (처음 본 행동으로 평가)

| 영상 | 예측 | 가장 높은 습관 | 점수 |
|---|---|---|---:|
| `X001_sit_still/P01_top_R01.mp4` | `other` | MOVEMENT | 0.16 |
| `X001_sit_still/P01_top_R02.mp4` | `other` | DRINK | 0.36 |
| `X001_sit_still/P01_top_R03.mp4` | `other` | MOVEMENT | 0.35 |
| `X002_phone_call/P01_top_R01.mp4` | `other` | MOVEMENT | 0.12 |
| `X002_phone_call/P01_top_R02.mp4` | `other` | MOVEMENT | 0.23 |
| `X002_phone_call/P01_top_R03.mp4` | `other` | MOVEMENT | 0.12 |
| `X003_hand_raise/P01_top_R01.mp4` | `other` | DRINK | 0.40 |
| `X003_hand_raise/P01_top_R03.mp4` | `drink_return` | DRINK | 0.51 |
| `X004_scratch_head/P01_top_R01.mp4` | `other` | MOVEMENT | 0.09 |
| `X004_scratch_head/P01_top_R02.mp4` | `other` | MOVEMENT | 0.32 |
| `X004_scratch_head/P01_top_R03.mp4` | `other` | MOVEMENT | 0.32 |
| `X005_touch_hair/P01_top_R01.mp4` | `other` | MOVEMENT | 0.07 |
| `X005_touch_hair/P01_top_R02.mp4` | `drink_return` | DRINK | 0.44 |
| `X005_touch_hair/P01_top_R03.mp4` | `other` | MOVEMENT | 0.51 |
| `X005_touch_hair/P01_top_R04.mp4` | `walk_turn_walk` | MOVEMENT | 0.59 |

> NG 영상이 P01·top 한 사람·한 각도뿐이고 전체 데이터도 적다. 이 숫자는 이 촬영 환경에서의 참고값이며 일반적인 정확도를 보장하지 않는다.
