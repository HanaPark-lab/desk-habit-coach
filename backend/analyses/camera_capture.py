"""허용된 IP Webcam에서 정해진 시간만 프레임을 받아 mp4로 저장한다 (Celery Worker가 실행)."""
import time

import cv2

from .services import AnalysisError

OUT_FPS = 12         # 저장 fps 고정. 12 = 학습 기준 6 Step/초의 정확한 배수 (15면 7.5 Step/초로 어긋남)
STALL_SECONDS = 3    # 이 시간 동안 새 프레임이 없으면 끊김으로 판단
TIMEOUT_MS = 5000


def capture(url, seconds, out_path):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, TIMEOUT_MS])
    if not cap.isOpened():
        raise AnalysisError("CAMERA_UNAVAILABLE", "카메라에 연결할 수 없습니다. IP Webcam 앱이 켜져 있고 같은 Wi-Fi인지 확인해 주세요.")
    writer, frame, written, total = None, None, 0, int(seconds * OUT_FPS)
    start = last_ok = time.monotonic()
    try:
        while written < total:
            ok, f = cap.read()
            now = time.monotonic()
            if ok:
                frame, last_ok = f, now
            elif now - last_ok > STALL_SECONDS:
                raise AnalysisError("CAMERA_LOST", "촬영 중 카메라 연결이 끊겼습니다.")
            if frame is None:
                continue
            if writer is None:
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), OUT_FPS, (w, h))
            # 흐른 시간만큼 프레임 칸을 채움 (카메라가 느리면 직전 프레임 반복)
            while written < total and start + written / OUT_FPS <= now:
                writer.write(frame)
                written += 1
    finally:
        cap.release()
        if writer is not None:
            writer.release()
