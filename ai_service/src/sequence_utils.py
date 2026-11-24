"""Step Feature 목록 → 고정 길이 30 Step Sequence(Window) = 1,140 Feature.

학습(training/train_rf.py)과 추론(FastAPI)이 같은 코드를 쓴다. 바꾸면 모델을 다시 학습해야 한다.
"""
import numpy as np

from .feature_utils import FEATURES_PER_STEP, KEYPOINTS, STEP_FEATURES

SEQ_STEPS = 30          # Window 길이 (Step)
TARGET_FPS = 6.0        # 초당 Step 수 → 30 Step = 5초
WINDOW_STRIDE = 6       # 다음 Window까지 6 Step(1초) 이동
MIN_VALID_RATIO = 0.5   # Window 안에서 관절이 잡힌 Step이 절반 미만이면 버림
ACTIVE_RATIO = 0.5      # 가장 많이 움직인 Window의 50% 미만이면 '쉬는 구간'으로 보고 제외


def feature_columns():
    """1,140개 Feature 이름. 순서 = Step 0의 38개, Step 1의 38개, ... (rf_feature_columns.json과 같아야 함)"""
    return [f"t{t:02d}_{f}" for t in range(SEQ_STEPS) for f in STEP_FEATURES]


def windows(steps):
    """Step 목록(배열 또는 None) → (Window 수, 1,140). 5초 미만이면 0행.

    빈 Step은 직전 값으로 채운다(맨 앞이 비면 첫 유효값으로).
    """
    out = []
    for start in range(0, len(steps) - SEQ_STEPS + 1, WINDOW_STRIDE):
        win = steps[start:start + SEQ_STEPS]
        valid = [s for s in win if s is not None]
        if len(valid) < SEQ_STEPS * MIN_VALID_RATIO:
            continue
        last, filled = valid[0], []
        for s in win:
            last = s if s is not None else last
            filled.append(last)
        out.append(np.concatenate(filled))
    if not out:
        return np.empty((0, SEQ_STEPS * FEATURES_PER_STEP), np.float32)
    return np.stack(out)


def window_motion(X):
    """Window별 움직임 양 = Step 사이 관절 좌표 변화의 평균 (각도 4개는 제외)."""
    coords = X.reshape(len(X), SEQ_STEPS, FEATURES_PER_STEP)[:, :, : len(KEYPOINTS) * 2]
    return np.abs(np.diff(coords, axis=1)).mean(axis=(1, 2))


def active_windows(X):
    """동작 앞뒤의 가만히 있는 Window를 뺀다. 학습과 추론이 반드시 같은 규칙을 쓴다."""
    if len(X) <= 1:
        return X
    motion = window_motion(X)
    return X[motion >= ACTIVE_RATIO * motion.max()]  # 전부 정지(max=0)면 모두 유지
