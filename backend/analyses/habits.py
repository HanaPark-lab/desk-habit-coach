"""모델 확률 → 기록할 행동 판정 (DRINK / MOVEMENT / "" = 기록 안 함)."""

OTHER_LABEL = "other"  # 학습한 행동이 아닌 동작(NG 영상으로 학습). 이 라벨이 최고면 기록하지 않음

EVENT_LABELS = {
    "DRINK": ("drink_return",),
    "MOVEMENT": ("wave", "walk_turn_walk"),  # 손 흔들기(어깨 풀기)·걷기 = 스트레칭·움직임
}


def event_scores(probabilities):
    return {e: sum(probabilities.get(label, 0.0) for label in labels) for e, labels in EVENT_LABELS.items()}


def top_event(probabilities):
    """한 사람의 확률 → (가장 높은 행동, 점수)."""
    scores = event_scores(probabilities)
    event = max(scores, key=scores.get)
    return event, scores[event]


def judge(predictions, thresholds):
    """사람별 결과 목록 → 기록할 행동 1개 (없으면 "").

    사람마다 점수가 가장 높은 행동을 고르고, 기준값을 넘은 것 중 가장 높은 1개만 기록한다 (작업당 최대 1건).
    """
    best, best_score = "", 0.0
    for p in predictions:
        if p["action_label"] == OTHER_LABEL:
            continue
        event, score = top_event(p["probabilities"])
        if score >= thresholds[event] and score > best_score:
            best, best_score = event, score
    return best
