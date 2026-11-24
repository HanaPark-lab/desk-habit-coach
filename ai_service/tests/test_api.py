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


def test_service_model_contract():
    import json

    from main import MODEL_DIR
    from services.model_loader import COLUMNS_FILE, load_bundle
    from src.sequence_utils import TARGET_FPS

    bundle = load_bundle(MODEL_DIR, "service")
    assert bundle.profile == "service"
    assert set(bundle.classes) == {"drink_return", "wave", "walk_turn_walk", "other"}
    assert bundle.model.n_features_in_ == 1140
    assert bundle.info["sequence_steps"] == SEQ_STEPS == 30
    assert bundle.info["features_per_step"] == FEATURES_PER_STEP == 38
    assert bundle.info["target_fps"] == TARGET_FPS == 6
    assert json.loads((MODEL_DIR / "service" / COLUMNS_FILE).read_text()) == feature_columns()


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
    body = client.post("/predict/frame", files={"frame": ("f.jpg", jpg.tobytes(), "image/jpeg")},
                       data={"detect_phone": "true", "stream_key": "t", "seq": 1}).json()
    assert body["persons"] and body["persons"][0]["index"] == 1 and len(body["persons"][0]["keypoints"]) == 17
    assert all(0 <= v <= 1 for v in body["persons"][0]["box"]) and isinstance(body["phones"], list)
    assert body["action_candidates"] == [] and body["buffer_steps"] == 0  # 여러 명 → 버퍼에 쌓지 않음
    assert body["model_profile"] == "service" and body["model_version"]


def test_presence_rules():
    from routers.predictions import presence
    good = [[0.5, 0.2, 0.9]] * 17
    blurry = [[0.5, 0.2, 0.1]] * 17
    me = {"box": [0.3, 0.1, 0.7, 0.9], "keypoints": good}
    side = {"box": [0.85, 0.1, 0.99, 0.9], "keypoints": good}  # 중심이 ROI 밖
    roi = (0.1, 0.0, 0.8, 1.0)
    assert presence([side, me], roi) == ({"track_count": 1, "quality_passed": True, "presence_candidate": True}, 1)
    assert presence([], roi) == ({"track_count": 0, "quality_passed": True, "presence_candidate": False}, None)  # 분명히 없음
    assert presence([me, {**me, "box": [0.2, 0.1, 0.6, 0.9]}], roi)[0]["presence_candidate"] is False          # 다중 인물
    assert presence([{**me, "keypoints": blurry}], roi)[0]["quality_passed"] is False                          # 가림·흐림


def test_stream_buffer_6fps_window_and_reset():
    from services import stream_buffer as sb
    buf, f = sb.StreamBuffers(), np.ones(FEATURES_PER_STEP, np.float32)
    step = sb.STEP_MS
    outs = [buf.add("s", i * step, f)[0] for i in range(42)]
    hits = [i for i, w in enumerate(outs) if w is not None]
    assert hits == [29, 35, 41] and outs[29].shape == (1, 1140)        # 30 Step에서 첫 Window, 이후 6 Step마다
    assert buf.add("s", 41 * step + 20, f) == (None, 30)               # 6fps보다 빠름 → 건너뜀
    assert buf.add("s", 41 * step + step * 3, f)[1] == 1               # 2 Step 넘게 빔 → 복제 없이 처음부터
    assert buf.add("s", 45 * step, None) == (None, 0)                  # 대상 불분명 → 비움
    assert buf.drop("s") and not buf.drop("s")


def test_stream_buffer_limits(monkeypatch):
    from services import stream_buffer as sb
    monkeypatch.setattr(sb, "MAX_STREAMS", 3)
    buf = sb.StreamBuffers()
    for k in "abcd":
        buf.add(k, 0, None)
    assert len(buf) == 3                                              # 가장 오래된 버퍼부터 제거
    monkeypatch.setattr(sb, "STREAM_TTL", -1)
    buf.add("e", 0, None)
    assert len(buf) == 1                                              # TTL 지난 버퍼 정리


def test_realtime_window_from_single_person_frames(client):
    one = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "zidane.jpg"))[:, :600]  # 1명만 보이게 자름
    jpg = cv2.imencode(".jpg", one)[1].tobytes()
    send = lambda i: client.post("/predict/frame", files={"frame": ("f.jpg", jpg, "image/jpeg")},
                                 data={"stream_key": "rt-test", "seq": int(i * 1000 / 6)}).json()
    bodies = [send(i) for i in range(30)]
    assert bodies[0]["presence_candidate"] and bodies[28]["buffer_steps"] == 29 and bodies[28]["action_candidates"] == []
    cands = bodies[29]["action_candidates"]                              # 30 Step(6fps 5초)에서 첫 결과
    assert [c["label"] for c in cands] and abs(sum(c["probability"] for c in cands) - 1) < 1e-3
    client.delete("/streams/rt-test")


def test_internal_token(client, monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_TOKEN", "s3cret")
    assert client.delete("/streams/x").status_code == 401
    assert client.delete("/streams/x", headers={"X-Internal-Token": "wrong"}).status_code == 401
    assert client.delete("/streams/x", headers={"X-Internal-Token": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # 상태 확인은 인증 없이


def test_delete_stream(client):
    client.app.state.streams.add("k1", 0, None)
    assert client.delete("/streams/k1").json() == {"dropped": True}
    assert client.delete("/streams/k1").json() == {"dropped": False}


def test_frame_roi_param(client):
    ok, jpg = cv2.imencode(".jpg", PEOPLE_IMG)
    send = lambda roi: client.post("/predict/frame", files={"frame": ("f.jpg", jpg.tobytes(), "image/jpeg")}, data={"roi": roi})
    body = send("0,0,1,1").json()
    assert body["track_count"] >= 2 and body["presence_candidate"] is False  # bus.jpg: 여러 명
    assert send("0.9,0,0.1,1").status_code == 422


def test_frame_invalid_image(client):
    r = client.post("/predict/frame", files={"frame": ("f.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "INVALID_FRAME"


def test_invalid_file(client, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    r = post(client, bad)
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "INVALID_VIDEO"
