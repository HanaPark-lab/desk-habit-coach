"""사람별 Window → Random Forest → Track ID별 대표 Action·Confidence."""
from src.sequence_utils import active_windows, windows


def predict_people(bundle, tracks):
    """tracks: {track_id: [Step Feature 또는 None]} → 사람별 예측 목록.

    쉬는 구간 Window를 뺀 뒤(학습과 같은 규칙) 확률을 평균해 가장 높은 동작을 대표 결과로 쓴다.
    probabilities(클래스 전부)도 함께 돌려줘서, 습관 판정은 Django가 한다.
    """
    results = []
    for tid in sorted(tracks):
        X = active_windows(windows(tracks[tid]))
        if len(X) == 0:
            continue
        proba = bundle.model.predict_proba(X).mean(axis=0)
        best = int(proba.argmax())
        results.append({
            "track_id": tid,
            "action_label": bundle.classes[best],
            "confidence": round(float(proba[best]), 4),
            "window_count": len(X),
            "probabilities": {c: round(float(p), 4) for c, p in zip(bundle.classes, proba)},
        })
    for i, r in enumerate(results, 1):
        r["track_id"] = i  # 영상 안에서 등장 순서대로 1부터. 영구 사람 ID가 아님
    return results
