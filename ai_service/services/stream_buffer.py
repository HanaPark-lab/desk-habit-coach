"""실시간 행동 분석용 세션별 30-step 버퍼 (메모리, 단일 FastAPI 프로세스 기준).

학습과 같은 입력 조건을 지킨다: 6fps(Step 간격 약 167ms), 30 Step = 5초, stride 6 Step.
- 너무 빨리 온 프레임(간격 < 0.5 Step)은 버린다 (6fps로 맞춤)
- 간격이 MAX_GAP_STEPS를 넘거나 대상이 분명하지 않으면(None) 버퍼를 비운다. 빠진 Step을 복제해 채우지 않는다.
- STREAM_TTL 동안 프레임이 없거나 MAX_STREAMS를 넘으면 오래된 버퍼부터 지운다. 서버 재시작 시 비어 있다.
"""
import threading
import time

import numpy as np

from src.sequence_utils import SEQ_STEPS, TARGET_FPS, WINDOW_STRIDE

STEP_MS = 1000 / TARGET_FPS
MAX_GAP_STEPS = 2
STREAM_TTL = 60.0   # 초
MAX_STREAMS = 20


class _Stream:
    __slots__ = ("steps", "last_ts", "since_pred", "touched")

    def __init__(self):
        self.steps, self.last_ts, self.since_pred, self.touched = [], None, 0, time.monotonic()


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
        for k in [k for k, s in self._streams.items() if now - s.touched > STREAM_TTL]:
            del self._streams[k]
        while len(self._streams) >= MAX_STREAMS:
            del self._streams[min(self._streams, key=lambda k: self._streams[k].touched)]

    def add(self, key, ts_ms, feature):
        """Step 하나 추가. 반환: (예측할 Window (1, 1140) 또는 None, 현재 버퍼 Step 수)."""
        now = time.monotonic()
        with self._lock:
            s = self._streams.get(key)
            if s is None:
                self._purge(now)
                s = self._streams[key] = _Stream()
            s.touched = now
            if s.last_ts is not None and 0 <= ts_ms - s.last_ts < STEP_MS * 0.5:
                return None, len(s.steps)                     # 6fps보다 빠름 → 이 프레임은 건너뜀
            gap = s.last_ts is not None and not (0 <= ts_ms - s.last_ts <= STEP_MS * MAX_GAP_STEPS)
            s.last_ts = ts_ms
            if feature is None or gap:
                s.steps, s.since_pred = [], 0                  # 대상 불분명·프레임 누락 → 처음부터
                if feature is None:
                    return None, 0
            s.steps.append(feature)
            del s.steps[:-SEQ_STEPS]
            s.since_pred += 1
            if len(s.steps) == SEQ_STEPS and s.since_pred >= WINDOW_STRIDE:  # 처음 찼을 때 + 이후 6 Step마다
                s.since_pred = 0
                return np.concatenate(s.steps)[None, :], SEQ_STEPS
            return None, len(s.steps)
