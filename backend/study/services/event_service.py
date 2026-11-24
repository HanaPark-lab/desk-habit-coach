"""분석 결과 → 행동 기록(BehaviorEvent). 작업 1건당 최대 1건 (dedup_key로 재처리에도 중복 없음)."""
from django.conf import settings

from analyses.habits import OTHER_LABEL, judge, top_event

from ..models import BehaviorEvent


def record_from_job(job, predictions):
    """기준을 통과한 행동이 있으면 기록하고 반환, 없으면 None."""
    profile = job.model_profile
    event_type = judge(predictions, settings.EVENT_THRESHOLDS, profile)
    if not event_type:
        return None
    candidates = [p for p in predictions if p["action_label"] != OTHER_LABEL and top_event(p["probabilities"], profile)[0] == event_type]
    best = max(candidates, key=lambda p: top_event(p["probabilities"], profile)[1])
    event, _ = BehaviorEvent.objects.get_or_create(
        dedup_key=f"job:{job.pk}",
        defaults={
            "user": job.user,
            "session": job.session,
            "job": job,
            "action_label": best["action_label"],
            "event_type": event_type,
            "confidence": round(top_event(best["probabilities"], profile)[1], 4),
            "occurred_at": job.created_at,
        },
    )
    return event
