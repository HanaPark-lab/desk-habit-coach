"""FastAPI 단독 검증 (가이드 2단계). models/service/에 서비스 모델이 있어야 한다.

실행 (ai_service 폴더에서):  ../.venv/bin/python -m pytest tests -q
"""
from pathlib import Path

import cv2
import numpy as np
import pytest
import ultralytics
from fastapi.testclient import TestClient

from main import app
from src.feature_utils import FEATURES_PER_STEP
from src.sequence_utils import SEQ_STEPS, active_windows, feature_columns, windows

PEOPLE_IMG = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg"))  # 사람 여러 명


def make_video(path, seconds, img):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (img.shape[1], img.shape[0]))
    for _ in range(int(seconds * 30)):
        w.write(img)
    w.release()
    return path


def post(client, path):
    with open(path, "rb") as f:
        return client.post("/predict/video", files={"file": (Path(path).name, f, "video/mp4")})


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_feature_spec():
    assert len(feature_columns()) == SEQ_STEPS * FEATURES_PER_STEP == 1140
    step = np.zeros(FEATURES_PER_STEP, np.float32)
    assert windows([step] * 29).shape == (0, 1140)               # 5초 미만 → Window 없음
    assert windows([None] + [step] * 29).shape == (1, 1140)      # 빈 Step은 채움
    assert windows([None] * 20 + [step] * 10).shape == (0, 1140)  # 유효 Step 절반 미만 → 버림


def test_active_windows_drops_idle():
    still = np.zeros(1140, np.float32)
    moving = np.tile(np.r_[np.full(FEATURES_PER_STEP, 0.0), np.full(FEATURES_PER_STEP, 1.0)], SEQ_STEPS // 2).astype(np.float32)
    assert active_windows(np.stack([still, moving, still])).shape == (1, 1140)  # 쉬는 Window 2개 제외
    assert active_windows(np.stack([still, still])).shape == (2, 1140)          # 전부 정지면 모두 유지


def test_model_profiles():
    from main import MODEL_DIR
    from services.model_loader import load_bundle
    assert load_bundle(MODEL_DIR, "service").profile == "service"
    for profile, msg in (("nope", "알 수 없는"), ("course", "모델 파일이 없습니다")):
        if profile == "course" and (MODEL_DIR / "course" / "rf_action_baseline.joblib").exists():
            assert len(load_bundle(MODEL_DIR, "course").classes) == 6  # 교과 모델을 넣은 경우
            continue
        with pytest.raises(RuntimeError, match=msg):
            load_bundle(MODEL_DIR, profile)


def test_health(client):
    body = client.get("/health").json()
    assert body["model_loaded"] and body["feature_count"] == 1140 and body["model_profile"] == "service"
    assert sorted(body["classes"]) == ["drink_return", "other", "walk_turn_walk", "wave"]


def test_people_video(client, tmp_path):
    body = post(client, make_video(tmp_path / "people.mp4", 6, PEOPLE_IMG)).json()
    preds = body["predictions"]
    assert preds and body["error_code"] == "" and body["model_profile"] == "service" and body["model_version"]
    assert [p["track_id"] for p in preds] == list(range(1, len(preds) + 1))
    for p in preds:
        assert p["action_label"] in p["probabilities"] and 0 <= p["confidence"] <= 1 and p["window_count"] >= 1


def test_no_person(client, tmp_path):
    r = post(client, make_video(tmp_path / "blank.mp4", 6, np.zeros_like(PEOPLE_IMG)))
    assert r.status_code == 200 and r.json()["predictions"] == [] and r.json()["error_code"] == "NO_PERSON"


def test_too_short(client, tmp_path):
    r = post(client, make_video(tmp_path / "short.mp4", 2, PEOPLE_IMG))
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "TOO_SHORT"


def test_frame_people_and_phone_fields(client):
    ok, jpg = cv2.imencode(".jpg", PEOPLE_IMG)
    body = client.post("/predict/frame", files={"frame": ("f.jpg", jpg.tobytes(), "image/jpeg")}).json()
    assert body["persons"] and body["persons"][0]["track_id"] == 1 and len(body["persons"][0]["keypoints"]) == 17
    assert all(0 <= v <= 1 for v in body["persons"][0]["box"]) and isinstance(body["phones"], list)


def test_frame_invalid_image(client):
    r = client.post("/predict/frame", files={"frame": ("f.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "INVALID_FRAME"


def test_invalid_file(client, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    r = post(client, bad)
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "INVALID_VIDEO"
