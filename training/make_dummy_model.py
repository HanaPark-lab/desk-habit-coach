"""가짜 모델: 진짜 모델과 파일 이름·형식·규격(4 Class, 1,140 Feature)이 같고 예측만 무작위.

진짜 학습 전에 FastAPI → Celery → Django 전체 흐름을 연결하는 용도. 예측 결과를 믿지 말 것.
실행 (프로젝트 폴더에서):  .venv/bin/python training/make_dummy_model.py
"""
import json
import sys
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ai_service"))
from src.feature_utils import FEATURES_PER_STEP  # noqa: E402  학습·추론이 같은 Feature 정의를 쓰기 위해
from src.sequence_utils import SEQ_STEPS, TARGET_FPS, WINDOW_STRIDE, feature_columns  # noqa: E402

# 실제 촬영한 3개 동작 (data/raw 폴더 ID와 같게)
ACTION_IDS = {"A001": "drink_return", "A002": "wave", "A003": "walk_turn_walk"}
OUT = ROOT / "ai_service" / "models"


def main():
    rng = np.random.default_rng(0)
    columns = feature_columns()
    X = rng.normal(size=(600, len(columns))).astype(np.float32)
    y = rng.choice(list(ACTION_IDS.values()), size=len(X))
    model = RandomForestClassifier(n_estimators=50, random_state=0).fit(X, y)

    info = {
        "model_version": "dummy-0",
        "is_dummy": True,
        "classes": [str(c) for c in model.classes_],
        "action_ids": ACTION_IDS,
        "sequence_steps": SEQ_STEPS,
        "features_per_step": FEATURES_PER_STEP,
        "n_features": len(columns),
        "target_fps": TARGET_FPS,
        "window_stride_steps": WINDOW_STRIDE,
        "sklearn_version": sklearn.__version__,
        "created_at": date.today().isoformat(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, OUT / "rf_action_baseline.joblib")
    (OUT / "rf_feature_columns.json").write_text(json.dumps(columns, indent=1), encoding="utf-8")
    (OUT / "rf_training_info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"저장: {OUT}  classes={info['classes']}  n_features={model.n_features_in_}")


if __name__ == "__main__":
    main()
