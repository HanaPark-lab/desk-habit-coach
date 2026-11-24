"""POST /predict/video: Celery Worker가 보낸 영상 → 사람별 동작.
POST /predict/frame: 집중 모드 프레임 1장 → 착석 후보·관절·(선택) 휴대폰·실시간 행동 후보 (저장하지 않음).
DELETE /streams/{key}: 실시간 버퍼 삭제."""
import os
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from services.action_inference import predict_people
from services.pose_pipeline import VideoError, _lock, track_people
from src.feature_utils import step_features
from src.sequence_utils import SEQ_STEPS, TARGET_FPS

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_FRAME_BYTES = 2 * 1024 * 1024
PHONE_CLASS = 67  # COCO "cell phone"
router = APIRouter()


def _norm_box(box, w, h):
    return [round(float(v) / d, 4) for v, d in zip(box, (w, h, w, h))]  # numpy → float (JSON 변환)


def _parse_roi(roi):
    if not roi:
        return (0.0, 0.0, 1.0, 1.0)
    try:
        x1, y1, x2, y2 = (float(v) for v in roi.split(","))
    except ValueError:
        x1 = None
    if x1 is None or not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise HTTPException(422, {"error_code": "INVALID_ROI", "message": "roi는 0~1 사이 x1,y1,x2,y2 입니다."})
    return x1, y1, x2, y2


def presence(persons, roi):
    """ROI(착석 영역) 안 사람 → (착석 후보 판단, 대상 사람의 persons 위치 또는 None). 사람 중심이 ROI 안이면 대상.

    quality_passed: ROI 안 모든 사람의 상체 관절(코·양 어깨)이 분명함 (0명이면 '분명히 없음'으로 통과)
    presence_candidate: ROI 안에 품질 통과한 사람이 정확히 1명
    """
    x1, y1, x2, y2 = roi
    inside = [i for i, p in enumerate(persons)
              if x1 <= (p["box"][0] + p["box"][2]) / 2 <= x2 and y1 <= (p["box"][1] + p["box"][3]) / 2 <= y2]
    clear = [i for i in inside if sum(persons[i]["keypoints"][k][2] for k in UPPER_BODY) / len(UPPER_BODY) >= MIN_KEYPOINT_CONF]
    quality = len(clear) == len(inside)
    candidate = quality and len(inside) == 1
    info = {"track_count": len(inside), "quality_passed": quality, "presence_candidate": candidate}
    return info, (inside[0] if candidate else None)


UPPER_BODY = (0, 5, 6)      # 코·왼어깨·오른어깨 (책상 앞 상반신 기준)
MIN_KEYPOINT_CONF = 0.5


@router.delete("/streams/{key}")
def drop_stream(request: Request, key: str):
    """세션 종료·휴식·카메라 끔 → 실시간 버퍼 삭제."""
    return {"dropped": request.app.state.streams.drop(key)}


@router.post("/predict/frame")
def predict_frame(request: Request, frame: UploadFile = File(...), roi: str = Form(""), stream_key: str = Form(""),
                  seq: int = Form(0), detect_phone: bool = Form(False)):
    """이미지 1장 → 사람(큰 순서로 번호 1, 2…; 프레임마다 새로 매김, 추적 ID 아님)·관절 17개·착석 후보.
    좌표는 0~1로 정규화. stream_key가 있으면 착석 대상 1명의 Feature를 세션 버퍼에 쌓고(seq = 관측 시각 ms),
    30 Step이 찰 때마다 action_candidates를 돌려준다. detect_phone=true일 때만 휴대폰을 찾는다."""
    start = time.perf_counter()
    region = _parse_roi(roi)
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
        det = state.detector.predict(img, classes=[PHONE_CLASS], conf=0.35, verbose=False)[0] if detect_phone else None
    persons, raw = [], []
    if len(pose.boxes):
        boxes = pose.boxes.xyxy.cpu().numpy()
        kxy = pose.keypoints.xy.cpu().numpy()
        kconf = pose.keypoints.conf.cpu().numpy()
        order = np.argsort(-(boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))  # 큰 사람부터
        for rank, i in enumerate(order, 1):
            persons.append({
                "index": rank,  # 이 프레임 안의 순번. 프레임 사이 같은 사람이라는 보장 없음
                "box": _norm_box(boxes[i], w, h),
                "keypoints": [[round(float(x) / w, 4), round(float(y) / h, 4), round(float(c), 3)] for (x, y), c in zip(kxy[i], kconf[i])],
            })
            raw.append((kxy[i], kconf[i]))
    phones = [] if det is None else [{"box": _norm_box(b, w, h), "confidence": round(float(c), 3)}
                                     for b, c in zip(det.boxes.xyxy.cpu().numpy(), det.boxes.conf.cpu().numpy())]
    info, target = presence(persons, region)

    candidates, buffer_steps = [], 0
    if stream_key:
        # 착석 대상이 정확히 1명일 때만 버퍼에 쌓음 (그 외에는 버퍼를 비워 다른 사람과 섞이지 않게)
        feature = step_features(*raw[target]) if target is not None else None
        window, buffer_steps = state.streams.add(stream_key, seq, feature)
        if window is not None:
            proba = state.bundle.model.predict_proba(window)[0]
            candidates = sorted(({"label": c, "probability": round(float(p), 4)} for c, p in zip(state.bundle.classes, proba)),
                                key=lambda x: -x["probability"])
    return {"persons": persons, "phones": phones, **info,
            "action_candidates": candidates, "buffer_steps": buffer_steps,
            "model_profile": state.bundle.profile, "model_version": state.bundle.version,
            "processing_ms": int((time.perf_counter() - start) * 1000)}


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
        "model_profile": state.bundle.profile,
        "model_version": state.bundle.version,
        "predictions": predictions,
        "error_code": error_code,
        "message": message,
        "processing_ms": int((time.perf_counter() - start) * 1000),
    }
