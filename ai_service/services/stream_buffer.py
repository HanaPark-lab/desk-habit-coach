"""세션별 6fps 슬롯과 학습용 Window 전처리를 사용하는 실시간 행동 버퍼."""
import threading
import time
from typing import NamedTuple

import numpy as np

from src.sequence_utils import SEQ_STEPS, TARGET_FPS, WINDOW_STRIDE, windows

STEP_MS = 1000 / TARGET_FPS
MAX_GAP_STEPS = 2
STREAM_TTL = 60.0
MAX_STREAMS = 20


class BufferResult(NamedTuple):
    window: np.ndarray | None
    steps: int
    valid_steps: int
    status: str


class _Stream:
    def __init__(self):
        self.steps = []
        self.anchor = None
        self.last_slot = -1
        self.next_window = SEQ_STEPS - 1
        self.touched = time.monotonic()

    def result(self, status, window=None):
        return BufferResult(window, len(self.steps), sum(step is not None for step in self.steps), status)


class StreamBuffers:
    def __init__(self):
        self._streams = {}
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._streams)

    def drop(self, key):
        with self._lock:
            return self._streams.pop(key, None) is not None

    def _purge(self, now):
        for key in [k for k, stream in self._streams.items() if now - stream.touched > STREAM_TTL]:
            del self._streams[key]
        while len(self._streams) >= MAX_STREAMS:
            del self._streams[min(self._streams, key=lambda k: self._streams[k].touched)]

    def add(self, key, ts_ms, feature):
        """한 슬롯에 한 프레임. 결측 Pose는 학습과 같은 유효률·보간 규칙으로 처리한다."""
        now = time.monotonic()
        with self._lock:
            stream = self._streams.get(key)
            if stream is None:
                self._purge(now)
                stream = self._streams[key] = _Stream()

            status = "collecting"
            if stream.anchor is not None:
                slot = round((ts_ms - stream.anchor) / STEP_MS)
                if slot <= stream.last_slot:
                    return stream.result("slot_already_sampled")
                if slot - stream.last_slot > MAX_GAP_STEPS or now - stream.touched > STREAM_TTL:
                    stream = self._streams[key] = _Stream()
                    status = "gap_reset"

            stream.touched = now
            if stream.anchor is None:
                stream.anchor = ts_ms
                slot = 0

            stream.steps.extend([None] * (slot - stream.last_slot - 1))
            stream.steps.append(feature)
            del stream.steps[:-SEQ_STEPS]
            stream.last_slot = slot
            if slot < stream.next_window:
                return stream.result(status)

            stream.next_window += WINDOW_STRIDE
            result = windows(stream.steps)
            if not len(result):
                return stream.result("insufficient_pose")
            return stream.result("window", result)
