"""영상 → YOLO Pose + Tracking → 사람(track)별 Step Feature 목록."""
import threading

import cv2

from src.feature_utils import step_features
from src.sequence_utils import TARGET_FPS


class VideoError(ValueError):
    """영상을 열거나 읽을 수 없음."""


_lock = threading.Lock()


def probe(path):
    cap = cv2.VideoCapture(str(path))
    ok = cap.isOpened() and cap.read()[0]
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    if not ok:
        raise VideoError("영상을 읽을 수 없습니다. 손상되었거나 지원하지 않는 형식입니다.")
    return fps if fps and fps > 0 else 30.0


def track_people(pose_model, path):
    """반환: ({yolo_track_id: [Step별 (38,) 또는 None]}, 전체 Step 수)."""
    stride = max(1, round(probe(path) / TARGET_FPS))
    per_track, n_steps = {}, 0
    # shortcut: YOLO tracker 상태를 공유하므로 영상 1개씩 처리. 동시 처리가 필요하면 FastAPI 프로세스를 늘린다.
    with _lock:
        results = pose_model.track(source=str(path), stream=True, vid_stride=stride, persist=False, verbose=False)
        for step, r in enumerate(results):
            n_steps = step + 1
            if r.boxes.id is None:
                continue
            xy = r.keypoints.xy.cpu().numpy()
            conf = r.keypoints.conf.cpu().numpy()
            for i, tid in enumerate(r.boxes.id.int().tolist()):
                per_track.setdefault(tid, {})[step] = step_features(xy[i], conf[i])
    tracks = {tid: [d.get(s) for s in range(n_steps)] for tid, d in per_track.items()}
    return tracks, n_steps
