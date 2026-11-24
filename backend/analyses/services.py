"""FastAPI 추론 서버 호출. 모든 실패는 AnalysisError(코드, 사용자용 메시지)로 바꾼다."""
from pathlib import Path

import requests
from django.conf import settings


def _auth():
    """Django·Celery → FastAPI 내부 인증 헤더 (AI_INTERNAL_TOKEN이 설정된 경우)."""
    return {"X-Internal-Token": settings.AI_INTERNAL_TOKEN} if settings.AI_INTERNAL_TOKEN else {}


class AnalysisError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def predict_video(path):
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"{settings.FASTAPI_URL}/predict/video",
                files={"file": (Path(path).name, f, "video/mp4")},
                headers=_auth(),
                timeout=(5, settings.FASTAPI_TIMEOUT),
            )
    except requests.Timeout:
        raise AnalysisError("AI_TIMEOUT", "AI 분석 시간이 초과되었습니다.")
    except requests.ConnectionError:
        raise AnalysisError("AI_UNAVAILABLE", "AI 분석 서버에 연결할 수 없습니다.")

    if r.status_code in (413, 422):  # FastAPI가 영상을 거부 (손상·너무 짧음·너무 큼)
        detail = r.json().get("detail", {})
        raise AnalysisError(detail.get("error_code", "INVALID_VIDEO"), detail.get("message", "영상을 분석할 수 없습니다."))
    if r.status_code == 401:
        raise AnalysisError("AI_AUTH", "AI 분석 서버 내부 인증에 실패했습니다 (AI_INTERNAL_TOKEN 확인).")
    if r.status_code != 200:
        raise AnalysisError("AI_ERROR", f"AI 분석 서버 오류 ({r.status_code})")
    try:
        body = r.json()
    except ValueError:
        raise AnalysisError("BAD_AI_RESPONSE", "AI 분석 결과 형식이 올바르지 않습니다.")
    _validate(body)
    return body


def drop_stream(key):
    """실시간 버퍼 삭제 (세션 종료·휴식·카메라 끔). 실패해도 FastAPI가 TTL로 정리하므로 무시."""
    try:
        requests.delete(f"{settings.FASTAPI_URL}/streams/{key}", headers=_auth(), timeout=(1, 2))
    except requests.RequestException:
        pass


def predict_frame(image_bytes, roi=None, stream_key="", seq=0, detect_phone=False):
    """집중 모드 프레임 1장 → FastAPI /predict/frame 결과 (착석 후보·관절·행동 후보…). 저장하지 않음."""
    data = {"stream_key": stream_key, "seq": seq, "detect_phone": str(bool(detect_phone)).lower()}
    if roi:
        data["roi"] = ",".join(str(v) for v in roi)
    try:
        r = requests.post(
            f"{settings.FASTAPI_URL}/predict/frame",
            files={"frame": ("frame.jpg", image_bytes, "image/jpeg")},
            data=data,
            headers=_auth(),
            timeout=(2, 10),
        )
    except requests.Timeout:
        raise AnalysisError("AI_TIMEOUT", "AI 분석 시간이 초과되었습니다.")
    except requests.ConnectionError:
        raise AnalysisError("AI_UNAVAILABLE", "AI 분석 서버에 연결할 수 없습니다.")
    if r.status_code != 200:
        detail = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("detail", {})
        raise AnalysisError(detail.get("error_code", "AI_ERROR"), detail.get("message", f"AI 분석 서버 오류 ({r.status_code})"))
    return r.json()


def _validate(body):
    """Worker가 저장하기 전에 응답 모양을 확인한다 (track_id 중복, 점수 범위, 라벨)."""
    try:
        preds = body["predictions"]
        ok = len({p["track_id"] for p in preds}) == len(preds) and all(
            0 <= p["confidence"] <= 1 and p["action_label"] in p["probabilities"] and p["window_count"] >= 1
            for p in preds
        )
    except (KeyError, TypeError):
        ok = False
    if not ok:
        raise AnalysisError("BAD_AI_RESPONSE", "AI 분석 결과 형식이 올바르지 않습니다.")
