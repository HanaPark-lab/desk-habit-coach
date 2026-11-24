"""카메라 중계 허브: 카메라 연결은 1개만 열고, 최신 JPEG 프레임을 여러 곳(미리보기·Celery 수집)에 나눠 준다.

DroidCam처럼 동시 접속이 1곳뿐인 카메라에서도 미리보기를 보면서 분석할 수 있게 한다. 프레임은 메모리에 최신 1장만 둔다.
"""
import threading
import time

import requests

IDLE_SECONDS = 15  # 아무도 보지 않으면 카메라 연결을 닫음


class CameraHub:
    def __init__(self, url):
        self.url = url
        self.frame = None
        self.seq = 0
        self.cond = threading.Condition()
        self.thread = None
        self.last_used = time.monotonic()

    def _run(self):
        buf = b""
        try:
            with requests.get(self.url, stream=True, timeout=(3, 10)) as r:
                r.raise_for_status()
                for chunk in r.iter_content(16384):
                    buf += chunk
                    while True:  # MJPEG에서 JPEG 한 장씩 잘라냄 (SOI FFD8 ~ EOI FFD9)
                        s = buf.find(b"\xff\xd8")
                        e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
                        if e < 0:
                            break
                        jpg, buf = buf[s:e + 2], buf[e + 2:]
                        with self.cond:
                            self.frame, self.seq = jpg, self.seq + 1
                            self.cond.notify_all()
                    if len(buf) > 5_000_000:
                        buf = b""
                    if time.monotonic() - self.last_used > IDLE_SECONDS:
                        break
        except requests.RequestException:
            pass  # 연결 실패·끊김 → 구독자들이 시간 초과로 종료
        finally:
            with self.cond:
                self.thread = None
                self.cond.notify_all()

    def frames(self, timeout=5):
        """새 프레임이 올 때마다 JPEG bytes를 내준다. timeout 동안 새 프레임이 없으면 끝."""
        with self.cond:
            if self.thread is None:
                self.last_used = time.monotonic()
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        last = 0
        while True:
            with self.cond:
                self.last_used = time.monotonic()
                if self.seq == last:
                    self.cond.wait(timeout)
                if self.seq == last:
                    return
                last, jpg = self.seq, self.frame
            yield jpg


_hubs = {}
_hubs_lock = threading.Lock()


def hub_for(key, url):
    with _hubs_lock:
        hub = _hubs.get(key)
        if hub is None or hub.url != url:
            hub = _hubs[key] = CameraHub(url)
        return hub


def mjpeg(frames):
    """JPEG 목록 → multipart/x-mixed-replace 스트림 (브라우저 <img>·OpenCV 모두 읽을 수 있음)."""
    for jpg in frames:
        yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
