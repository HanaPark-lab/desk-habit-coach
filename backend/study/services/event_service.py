"""분석 결과 → 행동 기록(BehaviorEvent).

- 클립: 작업 1건당 최대 1건 (dedup_key=job). 여러 사람이 보이면 대상이 불명확해 보류.
- 실시간: Window 결과가 기준을 넘는 연속 구간(episode)의 시작에서만 1건. episode가 끝난 뒤
  같은 행동이 다시 나와도 COOLDOWN 안이면 기록하지 않음.
- 클립과 실시간이 같은 행동을 COOLDOWN 안에 기록하면 먼저 기록된 1건만 남긴다.
"""
from datetime import datetime, timedelta
from typing import NamedTuple

from django.conf import settings
from django.db import transaction

from analyses.habits import OTHER_LABEL, event_label, judge, records_habits, top_event

from ..models import BehaviorEvent, StudySession

COOLDOWN = timedelta(seconds=60)
Source = BehaviorEvent.Source


def _duplicate_nearby(user, event_type, label, at, sources):
    return BehaviorEvent.objects.filter(
        user=user, event_type=event_type, action_label=label, is_valid=True, source__in=sources,
        occurred_at__gte=at - COOLDOWN, occurred_at__lte=at + COOLDOWN,
    ).exists()


def record_from_job(job, predictions):
    """기준을 통과한 행동이 있으면 기록하고 반환, 없으면 None."""
    profile = job.model_profile
    event_type = judge(predictions, settings.EVENT_THRESHOLDS, profile)
    if not event_type:
        return None
    existing = BehaviorEvent.objects.filter(dedup_key=f"job:{job.pk}").first()
    if existing:
        return existing
    probabilities = predictions[0]["probabilities"]
    label = event_label(probabilities, event_type, profile)
    if _duplicate_nearby(job.user, event_type, label, job.created_at, [Source.REALTIME]):
        return None  # 실시간 분석이 이미 같은 행동을 기록함
    event, _ = BehaviorEvent.objects.get_or_create(
        dedup_key=f"job:{job.pk}",
        defaults={
            "user": job.user,
            "session": job.session,
            "job": job,
            "action_label": label,
            "event_type": event_type,
            "confidence": round(top_event(probabilities, profile)[1], 4),
            "occurred_at": job.created_at,
            "source": Source.CLIP,
            "model_version": job.model_version,
        },
    )
    return event


class RealtimeDecision(NamedTuple):
    event: BehaviorEvent | None
    reason: str
    score: float | None = None
    threshold: float | None = None


def record_realtime_decision(session, candidates, profile, model_version, at):
    """Apply existing event policy and report why the window did or did not produce a record."""
    if not candidates:
        return RealtimeDecision(None, "no_window")
    if not records_habits(profile):
        return RealtimeDecision(None, "unsupported_profile")
    probs = {c["label"]: c["probability"] for c in candidates}
    event_type, score = top_event(probs, profile)
    threshold = settings.EVENT_THRESHOLDS[event_type]
    if candidates[0]["label"] == OTHER_LABEL:
        reason = "other"
    elif score < threshold:
        reason = "below_threshold"
    else:
        reason = "candidate"
    label = event_label(probs, event_type, profile) if reason == "candidate" else ""
    with transaction.atomic():
        s = StudySession.objects.select_for_update().get(pk=session.pk)
        if s.status != StudySession.Status.ACTIVE:
            return RealtimeDecision(None, "inactive_session", score, threshold)
        state = dict(s.realtime_state or {})
        recorded = None
        if label:
            last = state.get("last", {}).get(label)
            if state.get("episode") == label:
                reason = "same_episode"
            elif last and at - datetime.fromisoformat(last) < COOLDOWN:
                reason = "cooldown"
            elif _duplicate_nearby(s.user, event_type, label, at, [Source.CLIP, Source.REALTIME]):
                reason = "duplicate_nearby"
            else:
                recorded = BehaviorEvent.objects.create(
                    user=s.user, session=s, action_label=label,
                    event_type=event_type, confidence=round(score, 4), occurred_at=at, source=Source.REALTIME,
                    model_version=model_version, dedup_key=f"rt:{s.pk}:{label}:{at.isoformat()}",
                )
                state.setdefault("last", {})[label] = at.isoformat()
                reason = "recorded"
        state["episode"] = label
        s.realtime_state = state
        s.save(update_fields=["realtime_state"])
    return RealtimeDecision(recorded, reason, score, threshold)
