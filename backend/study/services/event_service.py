"""분석 결과 → 행동 기록(BehaviorEvent).

- 클립: 작업 1건당 최대 1건 (dedup_key=job). 여러 사람이 보이면 대상이 불명확해 보류.
- 실시간: Window 결과가 기준을 넘는 연속 구간(episode)의 시작에서만 1건. episode가 끝난 뒤
  같은 행동이 다시 나와도 COOLDOWN 안이면 기록하지 않음.
- 클립과 실시간이 같은 행동을 COOLDOWN 안에 기록하면 먼저 기록된 1건만 남긴다.
"""
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction

from analyses.habits import OTHER_LABEL, event_label, judge, records_habits, top_event

from ..models import BehaviorEvent, StudySession

COOLDOWN = timedelta(seconds=60)
Source = BehaviorEvent.Source


def _duplicate_nearby(user, event_type, at, sources):
    return BehaviorEvent.objects.filter(
        user=user, event_type=event_type, is_valid=True, source__in=sources,
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
    if _duplicate_nearby(job.user, event_type, job.created_at, [Source.REALTIME]):
        return None  # 실시간 분석이 이미 같은 행동을 기록함
    best = predictions[0]
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
            "source": Source.CLIP,
            "model_version": job.model_version,
        },
    )
    return event


def record_realtime(session, candidates, profile, model_version, at):
    """실시간 Window 1개의 결과(action_candidates) 반영. 새로 기록하면 BehaviorEvent, 아니면 None.

    candidates는 착석 대상 1명·품질 통과 프레임만으로 만든 Window의 결과다 (FastAPI 버퍼 규칙).
    """
    if not candidates or not records_habits(profile):
        return None
    probs = {c["label"]: c["probability"] for c in candidates}
    event_type, score = top_event(probs, profile)
    hit = event_type if candidates[0]["label"] != OTHER_LABEL and score >= settings.EVENT_THRESHOLDS[event_type] else ""
    with transaction.atomic():
        s = StudySession.objects.select_for_update().get(pk=session.pk)
        if s.status != StudySession.Status.ACTIVE:
            return None
        state = dict(s.realtime_state or {})
        recorded = None
        if hit and state.get("episode") != hit:  # 새 episode 시작
            last = state.get("last", {}).get(hit)
            cooled = not last or at - datetime.fromisoformat(last) >= COOLDOWN
            if cooled and not _duplicate_nearby(s.user, hit, at, [Source.CLIP, Source.REALTIME]):
                recorded = BehaviorEvent.objects.create(
                    user=s.user, session=s, action_label=event_label(probs, hit, profile),
                    event_type=hit, confidence=round(score, 4), occurred_at=at, source=Source.REALTIME,
                    model_version=model_version, dedup_key=f"rt:{s.pk}:{hit}:{at.isoformat()}",
                )
                state.setdefault("last", {})[hit] = at.isoformat()
        state["episode"] = hit
        s.realtime_state = state
        s.save(update_fields=["realtime_state"])
    return recorded
