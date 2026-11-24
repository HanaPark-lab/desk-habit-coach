"""관절 정규화와 Step당 38차원 Feature 계산 (COCO 17 Keypoint 기준).

학습(training/train_rf.py)과 추론(FastAPI)이 같은 코드를 쓴다. 바꾸면 모델을 다시 학습해야 한다.
"""
import numpy as np

KP_CONF = 0.3  # 이 값 미만 관절은 '안 보임'으로 보고 0 처리

KEYPOINTS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
ANGLES = ["left_elbow_angle", "right_elbow_angle", "left_shoulder_angle", "right_shoulder_angle"]
STEP_FEATURES = [f"{k}_{axis}" for k in KEYPOINTS for axis in ("x", "y")] + ANGLES
FEATURES_PER_STEP = len(STEP_FEATURES)  # 38 = 좌표 34 + 각도 4
L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 5, 6, 7, 8, 9, 10


def _angle(a, b, c):
    """b에서 a-b-c가 이루는 각도, 0~1 (π = 1)."""
    v1, v2 = a - b, c - b
    n = np.linalg.norm(v1) * np.linalg.norm(v2)
    if n < 1e-6:
        return 0.0
    return float(np.arccos(np.clip(v1 @ v2 / n, -1.0, 1.0)) / np.pi)


def step_features(xy, conf):
    """한 사람의 한 프레임: xy (17,2) 픽셀, conf (17,) → (38,) 또는 None.

    어깨 중심을 원점, 어깨 너비를 1로 정규화한다. 앉은 상반신 화면에서 골반은
    잘릴 수 있지만 어깨는 항상 보이므로, 어깨가 안 보이면 None(빈 Step)으로 둔다.
    """
    if conf[L_SH] < KP_CONF or conf[R_SH] < KP_CONF:
        return None
    center = (xy[L_SH] + xy[R_SH]) / 2
    scale = np.linalg.norm(xy[L_SH] - xy[R_SH])
    if scale < 1e-3:
        return None
    vis = conf >= KP_CONF
    norm = np.where(vis[:, None], (xy - center) / scale, 0.0)

    def elbow(s, e, w):
        return _angle(norm[s], norm[e], norm[w]) if vis[s] and vis[e] and vis[w] else 0.0

    def shoulder(s, e):  # 위팔이 아래 방향(0,1)에서 들린 정도: 0 = 내림, 1 = 머리 위
        return _angle(norm[s] + (0.0, 1.0), norm[s], norm[e]) if vis[s] and vis[e] else 0.0

    angles = [elbow(L_SH, L_EL, L_WR), elbow(R_SH, R_EL, R_WR), shoulder(L_SH, L_EL), shoulder(R_SH, R_EL)]
    return np.concatenate([norm.ravel(), angles]).astype(np.float32)
