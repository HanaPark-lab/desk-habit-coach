"""공부 세션 시간 엔진: 상태 구간(StudyInterval)을 겹치지 않게 열고 닫고, 시간을 집계한다.

1단계(수동 타이머): 시작·휴식·재개·종료 버튼으로 구간을 바꾼다.
화면이 heartbeat를 보내지 않은 시간은 공부로 세지 않고 UNKNOWN(확인 불가)으로 정산한다.
"""
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from ..models import BehaviorEvent, StudyInterval, StudySession

Status = StudySession.Status
State = StudyInterval.State
HEARTBEAT_TIMEOUT = timedelta(seconds=90)  # 화면 신호가 이 시간 넘게 없으면 끊긴 것으로 봄


class SessionError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message, self.status = message, status


def open_session(user):
    return StudySession.objects.filter(user=user).exclude(status=Status.ENDED).first()


def _is_stale(session, now):
    return session.last_seen_at is not None and now - session.last_seen_at > HEARTBEAT_TIMEOUT


def _current(session):
    return session.intervals.filter(ended_at__isnull=True).first()


def _settle_gap(session, now):
    """공부 중에 신호가 끊겼던 시간은 UNKNOWN으로 바꾼다. 수동 휴식(BREAK)은 사용자 입력이라 그대로 둔다."""
    cur = _current(session)
    if cur and cur.state == State.STUDY and _is_stale(session, now):
        cur.ended_at = max(cur.started_at, session.last_seen_at)
        cur.save(update_fields=["ended_at"])
        StudyInterval.objects.create(session=session, state=State.UNKNOWN, started_at=cur.ended_at)


def start(user):
    now = timezone.now()
    try:
        with transaction.atomic():
            session = StudySession.objects.create(user=user, started_at=now, last_seen_at=now)
            StudyInterval.objects.create(session=session, state=State.STUDY, started_at=now)
    except IntegrityError:  # one_open_session_per_user: 동시 요청에도 열린 세션은 하나
        raise SessionError("이미 진행 중인 공부 세션이 있습니다.")
    return session


def _change(session, allowed, new_state, new_status, message):
    now = timezone.now()
    with transaction.atomic():
        s = StudySession.objects.select_for_update().get(pk=session.pk)  # 같은 세션 동시 변경 방지
        if s.status not in allowed:
            raise SessionError(message)
        _settle_gap(s, now)
        cur = _current(s)
        if cur:
            cur.ended_at = now
            cur.save(update_fields=["ended_at"])
        if new_state:
            StudyInterval.objects.create(session=s, state=new_state, started_at=now)
        s.status, s.last_seen_at = new_status, now
        if new_status == Status.ENDED:
            s.ended_at = now
        s.save()
    return s


def pause(session):
    return _change(session, {Status.ACTIVE}, State.BREAK, Status.PAUSED, "공부 중일 때만 휴식할 수 있습니다.")


def resume(session):
    return _change(session, {Status.PAUSED}, State.STUDY, Status.ACTIVE, "휴식 중일 때만 재개할 수 있습니다.")


def end(session):
    return _change(session, {Status.ACTIVE, Status.PAUSED}, None, Status.ENDED, "이미 종료된 세션입니다.")


def heartbeat(session):
    """화면이 열려 있다는 신호. 끊겼다가 돌아오면 UNKNOWN 구간을 닫고 다시 공부로."""
    now = timezone.now()
    with transaction.atomic():
        s = StudySession.objects.select_for_update().get(pk=session.pk)
        if s.status == Status.ENDED:
            raise SessionError("이미 종료된 세션입니다.")
        _settle_gap(s, now)
        cur = _current(s)
        if s.status == Status.ACTIVE and cur and cur.state == State.UNKNOWN:
            cur.ended_at = now
            cur.save(update_fields=["ended_at"])
            StudyInterval.objects.create(session=s, state=State.STUDY, started_at=now)
        s.last_seen_at = now
        s.save(update_fields=["last_seen_at"])
    return s


AWAY_AFTER = timedelta(seconds=5)          # 사람이 이 시간 넘게 안 보이면 자리 비움 (AI_PIPELINE.md 초기값)
PHONE_ALERT_AFTER = timedelta(seconds=10)  # 휴대폰이 이 시간 넘게 계속 보이면 집중 이탈 1회


def observe(session, present, phone_confidence=None):
    """집중 모드 프레임 1장의 결과 반영 (heartbeat 역할 포함).

    - 사람 없음이 AWAY_AFTER 이상 → STUDY를 마지막으로 보인 시각에서 닫고 AWAY (자동)
    - 다시 보임 → AWAY/UNKNOWN을 닫고 STUDY (자동). 수동 휴식(PAUSED) 중에는 건드리지 않음
    - 휴대폰이 PHONE_ALERT_AFTER 이상 연속 → 집중 이탈 기록 1건 (연속 구간당 1건)
    반환: (세션, 이번 프레임에서 알림을 띄울지)
    """
    now = timezone.now()
    alert = False
    with transaction.atomic():
        s = StudySession.objects.select_for_update().get(pk=session.pk)
        if s.status == Status.ENDED:
            raise SessionError("이미 종료된 세션입니다.")
        _settle_gap(s, now)
        cur = _current(s)
        if s.status == Status.ACTIVE and cur:
            if present:
                s.last_present_at = now
                if cur.state in (State.AWAY, State.UNKNOWN):
                    cur.ended_at = now
                    cur.save(update_fields=["ended_at"])
                    StudyInterval.objects.create(session=s, state=State.STUDY, started_at=now, source=StudyInterval.Source.AUTO)
            else:
                since = max(s.last_present_at or cur.started_at, cur.started_at)
                if cur.state == State.STUDY and now - since >= AWAY_AFTER:
                    cur.ended_at = since
                    cur.save(update_fields=["ended_at"])
                    StudyInterval.objects.create(session=s, state=State.AWAY, started_at=since, source=StudyInterval.Source.AUTO)
        if phone_confidence is not None and s.status == Status.ACTIVE:
            s.phone_since = s.phone_since or now
            if now - s.phone_since >= PHONE_ALERT_AFTER:
                _, alert = BehaviorEvent.objects.get_or_create(
                    dedup_key=f"phone:{s.pk}:{s.phone_since.isoformat()}",
                    defaults={"user": s.user, "session": s, "action_label": "cell_phone",
                              "event_type": BehaviorEvent.EventType.PHONE, "confidence": phone_confidence,
                              "occurred_at": s.phone_since},
                )
        else:
            s.phone_since = None
        s.last_seen_at = now
        s.save()
    return s, alert


# ---- 집계 ----

def _segments(interval, now):
    """구간 → (상태, 시작, 끝) 목록. 열린 공부 구간인데 신호가 끊겼으면 끊긴 뒤는 UNKNOWN."""
    if interval.ended_at:
        return [(interval.state, interval.started_at, interval.ended_at)]
    s = interval.session
    if interval.state == State.STUDY and s.status != Status.ENDED and _is_stale(s, now):
        cut = max(interval.started_at, s.last_seen_at)
        return [(State.STUDY, interval.started_at, cut), (State.UNKNOWN, cut, now)]
    return [(interval.state, interval.started_at, now)]


def seconds_by_state(intervals, start=None, end=None, now=None):
    """구간들을 [start, end) 범위로 잘라 상태별 초 합계."""
    now = now or timezone.now()
    totals = dict.fromkeys(State.values, 0)
    for iv in intervals:
        for state, a, b in _segments(iv, now):
            a, b = max(a, start) if start else a, min(b, end) if end else b
            if b > a:
                totals[state] += int((b - a).total_seconds())
    return totals


def segments_between(intervals, start, end, now=None):
    """타임라인용: [start, end)로 자른 (상태, 시작, 끝) 목록."""
    now = now or timezone.now()
    out = []
    for iv in intervals:
        for state, a, b in _segments(iv, now):
            a, b = max(a, start), min(b, end)
            if b > a:
                out.append((state, a, b))
    return out


def day_range(day):
    """그 날짜의 Asia/Seoul 자정 ~ 다음 자정 (aware datetime)."""
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def intervals_between(user, start, end):
    return (StudyInterval.objects.select_related("session")
            .filter(session__user=user, started_at__lt=end)
            .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=start)))


def day_seconds(user, day, now=None):
    start, end = day_range(day)
    return seconds_by_state(intervals_between(user, start, end), start, end, now)
