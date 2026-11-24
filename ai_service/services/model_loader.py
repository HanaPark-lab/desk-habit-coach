"""모델 파일 3개(Joblib·Feature 순서 JSON·학습 정보 JSON)를 읽고 규격이 맞는지 검사한다 (T01)."""
import json
from dataclasses import dataclass
from pathlib import Path

import joblib

from src.feature_utils import FEATURES_PER_STEP
from src.sequence_utils import SEQ_STEPS, feature_columns

MODEL_FILE = "rf_action_baseline.joblib"
COLUMNS_FILE = "rf_feature_columns.json"
INFO_FILE = "rf_training_info.json"


@dataclass
class ModelBundle:
    model: object
    info: dict

    @property
    def version(self):
        return self.info.get("model_version", "unknown")

    @property
    def classes(self):
        return [str(c) for c in self.model.classes_]


def load_bundle(model_dir):
    d = Path(model_dir)
    model = joblib.load(d / MODEL_FILE)  # 직접 만든 신뢰 가능한 파일에만 joblib.load 사용
    columns = json.loads((d / COLUMNS_FILE).read_text(encoding="utf-8"))
    info = json.loads((d / INFO_FILE).read_text(encoding="utf-8"))

    expected = feature_columns()
    problems = []
    if columns != expected:
        problems.append(f"{COLUMNS_FILE}의 Feature 이름·순서가 src/sequence_utils.py와 다름")
    if model.n_features_in_ != len(expected):
        problems.append(f"모델 입력 {model.n_features_in_}개 != {len(expected)}개")
    if info.get("sequence_steps") != SEQ_STEPS or info.get("features_per_step") != FEATURES_PER_STEP:
        problems.append(f"{INFO_FILE}의 Step 규격이 {SEQ_STEPS}x{FEATURES_PER_STEP}가 아님")
    if [str(c) for c in model.classes_] != info.get("classes"):
        problems.append(f"model.classes_와 {INFO_FILE}의 classes가 다름")
    if problems:
        raise RuntimeError("모델 규격 불일치: " + "; ".join(problems))
    return ModelBundle(model, info)
