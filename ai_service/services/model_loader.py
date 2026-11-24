"""모델 프로필별 파일 3개(Joblib·Feature 순서 JSON·학습 정보 JSON)를 읽고 규격이 맞는지 검사한다 (T01).

models/<프로필>/ 아래에 둔다. 두 모델은 클래스·ID 체계가 달라 섞지 않는다.
- service: 자체 촬영 4종 (drink_return, wave, walk_turn_walk, other) → 습관 기록에 사용
- course : 교과 제공 6종 RF 모델 → 교과 제출 실행용 (습관 기록 안 함)
"""
import json
from dataclasses import dataclass
from pathlib import Path

import joblib

from src.feature_utils import FEATURES_PER_STEP
from src.sequence_utils import SEQ_STEPS, TARGET_FPS, WINDOW_STRIDE, feature_columns

MODEL_FILE = "rf_action_baseline.joblib"
COLUMNS_FILE = "rf_feature_columns.json"
INFO_FILE = "rf_training_info.json"
PROFILES = {
    "service": {"classes": ["drink_return", "other", "walk_turn_walk", "wave"]},
    "course": {"n_classes": 6},  # 교과 라벨 이름은 모델 파일의 classes를 따른다
}


@dataclass
class ModelBundle:
    model: object
    info: dict
    profile: str

    @property
    def version(self):
        return self.info.get("model_version", "unknown")

    @property
    def classes(self):
        return [str(c) for c in self.model.classes_]


def load_bundle(model_root, profile):
    if profile not in PROFILES:
        raise RuntimeError(f"알 수 없는 MODEL_PROFILE '{profile}' (가능: {', '.join(PROFILES)})")
    d = Path(model_root) / profile
    missing = [f for f in (MODEL_FILE, COLUMNS_FILE, INFO_FILE) if not (d / f).exists()]
    if missing:
        raise RuntimeError(f"{profile} 프로필 모델 파일이 없습니다: {d} ({', '.join(missing)})")
    model = joblib.load(d / MODEL_FILE)  # 직접 만든 신뢰 가능한 파일에만 joblib.load 사용
    columns = json.loads((d / COLUMNS_FILE).read_text(encoding="utf-8"))
    info = json.loads((d / INFO_FILE).read_text(encoding="utf-8"))

    expected = feature_columns()
    classes = [str(c) for c in model.classes_]
    spec = PROFILES[profile]
    problems = []
    if columns != expected:
        problems.append(f"{COLUMNS_FILE}의 Feature 이름·순서가 src/sequence_utils.py와 다름")
    if model.n_features_in_ != len(expected):
        problems.append(f"모델 입력 {model.n_features_in_}개 != {len(expected)}개")
    if info.get("sequence_steps") != SEQ_STEPS or info.get("features_per_step") != FEATURES_PER_STEP:
        problems.append(f"{INFO_FILE}의 Step 규격이 {SEQ_STEPS}x{FEATURES_PER_STEP}가 아님")
    if info.get("target_fps") != TARGET_FPS or info.get("window_stride_steps") != WINDOW_STRIDE:
        problems.append(f"{INFO_FILE}의 샘플링이 {TARGET_FPS}fps·stride {WINDOW_STRIDE}가 아님")
    if classes != info.get("classes"):
        problems.append(f"model.classes_와 {INFO_FILE}의 classes가 다름")
    if "classes" in spec and classes != spec["classes"]:
        problems.append(f"{profile} 클래스가 {spec['classes']}가 아님: {classes}")
    if "n_classes" in spec and len(classes) != spec["n_classes"]:
        problems.append(f"{profile} 클래스가 {spec['n_classes']}종이 아님: {classes}")
    if problems:
        raise RuntimeError("모델 규격 불일치: " + "; ".join(problems))
    return ModelBundle(model, info, profile)
