"""FastAPI 추론 서버. DB는 모르고, 영상을 받아 사람별 결과 JSON만 돌려준다.

실행 (ai_service 폴더에서):  uvicorn main:app --port 8001
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from ultralytics import YOLO

from routers.predictions import router as predictions_router
from services.model_loader import load_bundle

MODEL_DIR = Path(os.getenv("MODEL_DIR", Path(__file__).resolve().parent / "models"))
POSE_WEIGHTS = os.getenv("POSE_WEIGHTS", str(MODEL_DIR / "yolo11n-pose.pt"))
DETECT_WEIGHTS = os.getenv("DETECT_WEIGHTS", str(MODEL_DIR / "yolo11n.pt"))  # 집중 모드 휴대폰 감지 (COCO)


@asynccontextmanager
async def lifespan(app):
    app.state.bundle = load_bundle(MODEL_DIR)  # 서버 시작 시 1번만 로드, 요청마다 재사용
    app.state.pose = YOLO(POSE_WEIGHTS)
    app.state.detector = YOLO(DETECT_WEIGHTS)
    yield


app = FastAPI(title="Desk Habit Coach AI", lifespan=lifespan)
app.include_router(predictions_router)


@app.get("/health")
def health():
    b = getattr(app.state, "bundle", None)
    return {
        "status": "ok",
        "model_loaded": b is not None,
        "model_version": b.version if b else None,
        "classes": b.classes if b else [],
        "feature_count": int(b.model.n_features_in_) if b else 0,
    }
