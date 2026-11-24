"""POST /predict/video: Celery Worker가 보낸 영상 → 사람별 동작.
POST /predict/frame: 집중 모드 프레임 1장 → 사람·관절·휴대폰 위치 (저장하지 않음)."""
import os
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from services.action_inference import predict_people
from services.pose_pipeline import VideoError, _lock, track_people
from src.sequence_utils import SEQ_STEPS, TARGET_FPS

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_FRAME_BYTES = 2 * 1024 * 1024
PHONE_CLASS = 67  # COCO "cell phone"
router = APIRouter()


def _norm_box(box, w, h):
    return [round(float(v) / d, 4) for v, d in zip(box, (w, h, w, h))]  # numpy → float (JSON 변환)


@router.post("/predict/frame")
def predict_frame(request: Request, frame: UploadFile = File(...)):
    """이미지 1장 → 사람(큰 순서로 track_id 1, 2…)·관절 17개·휴대폰 상자. 좌표는 0~1로 정규화."""
    start = time.perf_counter()
    data = frame.file.read(MAX_FRAME_BYTES + 1)
    if len(data) > MAX_FRAME_BYTES:
        raise HTTPException(413, {"error_code": "TOO_LARGE", "message": "프레임이 너무 큽니다."})
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(422, {"error_code": "INVALID_FRAME", "message": "이미지를 읽을 수 없습니다."})
    h, w = img.shape[:2]
    state = request.app.state
    with _lock:  # 영상 분석과 같은 모델을 공유하므로 한 번에 하나씩
        pose = state.pose.predict(img, verbose=False)[0]
        det = state.detector.predict(img, classes=[PHONE_CLASS], conf=0.35, verbose=False)[0]
    persons = []
    if len(pose.boxes):
        boxes = pose.boxes.xyxy.cpu().numpy()
        kxy = pose.keypoints.xy.cpu().numpy()
        kconf = pose.keypoints.conf.cpu().numpy()
        order = np.argsort(-(boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))  # 큰 사람 = 촬영 대상
        for rank, i in enumerate(order, 1):
            persons.append({
                "track_id": rank,
                "box": _norm_box(boxes[i], w, h),
                "keypoints": [[round(float(x) / w, 4), round(float(y) / h, 4), round(float(c), 3)] for (x, y), c in zip(kxy[i], kconf[i])],
            })
    phones = [{"box": _norm_box(b, w, h), "confidence": round(float(c), 3)}
              for b, c in zip(det.boxes.xyxy.cpu().numpy(), det.boxes.conf.cpu().numpy())]
    return {"persons": persons, "phones": phones, "processing_ms": int((time.perf_counter() - start) * 1000)}


@router.post("/predict/video")
def predict_video(request: Request, file: UploadFile = File(...)):
    # def(동기)로 선언 → FastAPI가 별도 스레드에서 실행해 서버가 멈추지 않음
    start = time.perf_counter()
    state = request.app.state
    tmp = tempfile.NamedTemporaryFile(suffix=Path(file.filename or "").suffix or ".mp4", delete=False)
    try:
        with tmp:
            size = 0
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_MB << 20:
                    raise HTTPException(413, {"error_code": "TOO_LARGE", "message": f"{MAX_UPLOAD_MB}MB 이하 영상만 받습니다."})
                tmp.write(chunk)
        tracks, n_steps = track_people(state.pose, tmp.name)
    except VideoError as e:
        raise HTTPException(422, {"error_code": "INVALID_VIDEO", "message": str(e)})
    finally:
        os.unlink(tmp.name)

    if n_steps < SEQ_STEPS:
        raise HTTPException(422, {"error_code": "TOO_SHORT", "message": f"영상이 너무 짧습니다. {SEQ_STEPS / TARGET_FPS:.0f}초 이상 필요합니다."})

    predictions = predict_people(state.bundle, tracks)
    if predictions:
        error_code, message = "", ""
    elif tracks:
        error_code, message = "NO_VALID_WINDOW", "사람이 분석할 만큼 오래 보이지 않았습니다."
    else:
        error_code, message = "NO_PERSON", "영상에서 사람을 찾지 못했습니다."
    return {
        "model_version": state.bundle.version,
        "predictions": predictions,
        "error_code": error_code,
        "message": message,
        "processing_ms": int((time.perf_counter() - start) * 1000),
    }
