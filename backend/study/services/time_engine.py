"""공부 세션 시간 엔진: 상태 구간(StudyInterval)을 겹치지 않게 열고 닫고, 시간을 집계한다.

두 모드를 구분한다 (수동 기록을 AI가 확인한 시간으로 표시하지 않음).
- MANUAL: 시작·휴식·재개·종료 버튼. heartbeat가 90초 넘게 없으면 끊긴 뒤 시간은 UNKNOWN.
- AI    : 카메라 관측. 시작·재개는 UNKNOWN → ROI 안 1명이 3초 안정 → STUDY (첫 관측 시각으로 소급),
          정상 프레임에서 부재 5초 → AWAY_PENDING (첫 미감지 시각으로 소급).
          복귀가 이탈 시작 후 15분 이내면 이탈 전체를 BREAK, 넘으면 전체를 AWAY로 확정 (같은 구간의 상태만 바꿈).
          마지막 유효 관측 후 timeout → UNKNOWN (끊긴 pending은 AWAY로 확정). heartbeat로 STUDY 복구 안 함.
수동 휴식(BREAK)은 두 모드 모두 사용자 입력이 우선이다. 휴식·종료·모드 전환 시 pending은 AWAY로 확정.
상태 API(current_state)와 집계(seconds_by_state)는 같은 정산 규칙(_stale_cut)을 쓴다.
"""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from ..models import BehaviorEvent, StudyInterval, StudySession

Status = StudySession.Status
Mode = StudySession.Mode
State = StudyInterval.State
Source = StudyInterval.Source
HEARTBEAT_TIMEOUT = timedelta(seconds=90)  # 수동 모드: 화면 신호가 이 시간 넘게 없으면 끊긴 것으로 봄
PRESENT_AFTER = timedelta(seconds=3)       # AI 모드: ROI 안 1명이 이만큼 안정적으로 보이면 STUDY
AWAY_AFTER = timedelta(seconds=5)          # AI 모드: 정상 프레임에서 부재가 이만큼 이어지면 AWAY_PENDING
BREAK_LIMIT = timedelta(seconds=900)       # 이 시간 안에 복귀하면 이탈 전체가 BREAK, 넘으면 AWAY (서비스 분류 규칙)
PHONE_ALERT_AFTER = timedelta(seconds=10)  # 휴대폰이 이 시간 넘게 계속 보이면 집중 이탈 1회


class SessionError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message, self.status = message, status


def ai_timeout():
    return timedelta(seconds=settings.AI_OBSERVATION_TIMEOUT_SECONDS)


def open_session(user):
    return StudySession.objects.filter(user=user).exclude(status=Status.ENDED).first()


def _current(session):
    return session.intervals.filter(ended_at__isnull=True).first()


def _stale_cut(session, interval, now):
    """열린 구간 중 '확인 불가'로 봐야 하는 부분의 시작 시각 (없으면 None)."""
    if interval.ended_at or session.status != Status.ACTIVE:
        return None
    if session.mode == Mode.AI:
        if interval.state in (State.STUDY, State.AWAY, State.AWAY_PENDING):
            last = max(session.last_observed_at or interval.started_at, interval.started_at)
            if now - last > ai_timeout():
                return last
    elif interval.state == State.STUDY and session.last_seen_at and now - session.last_seen_at > HEARTBEAT_TIMEOUT:
        return max(interval.started_at, session.last_seen_at)
    return None


def _entry(mode):
    """모드 진입(시작·재개·전환) 시 여는 구간."""
    return (State.UNKNOWN, Source.AUTO) if mode == Mode.AI else (State.STUDY, Source.MANUAL)


def _switch(session, cur, state, at, source):
    """cur를 at에서 닫고 새 구간을 연다."""
    if cur:
        cur.ended_at = at
        cur.save(update_fields=["ended_at"])
    StudyInterval.objects.create(session=session, state=state, started_at=at, source=source)


def _reset_candidates(s):
    s.presence_since = s.absent_since = None


def _confirm_pending(cur, state):
    """복귀 확인 중이던 이탈 구간 전체를 BREAK 또는 AWAY로 확정 (구간을 나누지 않음)."""
    if cur and cur.state == State.AWAY_PENDING:
        cur.state = state
        cur.save(update_fields=["state"])


def _settle_gap(s, now):
    """끊긴 시간을 UNKNOWN으로 확정한다. 수동 휴식(BREAK)은 건드리지 않는다."""
    cur = _current(s)
    cut = cur and _stale_cut(s, cur, now)
    if cut:
        _confirm_pending(cur, State.AWAY)  # 복귀 확인 없이 끊긴 이탈은 AWAY
        _switch(s, cur, State.UNKNOWN, cut, Source.AUTO if s.mode == Mode.AI else Source.MANUAL)
        _reset_candidates(s)


def current_state(session, now=None):
    """(상태, 시작 시각). 열린 구간에 정산 규칙을 적용한 값 (DB를 바꾸지 않음)."""
    now = now or timezone.now()
    cur = next((i for i in session.intervals.all() if i.ended_at is None), None)
    if not cur:
        return None, None
    cut = _stale_cut(session, cur, now)
    return (State.UNKNOWN, cut) if cut else (cur.state, cur.started_at)


def _locked(session):
    s = StudySession.objects.select_for_update().get(pk=session.pk)  # 같은 세션 동시 변경 방지
    if s.status == Status.ENDED:
        raise SessionError("이미 종료된 세션입니다.")
    return s


def start(user, mode=Mode.MANUAL):
    now = timezone.now()
    try:
        with transaction.atomic():
            session = StudySession.objects.create(user=user, started_at=now, last_seen_at=now, mode=mode)
            state, source = _entry(mode)
            StudyInterval.objects.create(session=session, state=state, started_at=now, source=source)
    except IntegrityError:  # one_open_session_per_user: 동시 요청에도 열린 세션은 하나
        raise SessionError("이미 진행 중인 공부 세션이 있습니다.")
    return session


def _change(session, allowed, new_status, message, new_state=None):
    """new_state: None(구간 없음) / "ENTRY"(모드 진입 구간) / State.*"""
    now = timezone.now()
    with transaction.atomic():
        s = StudySession.objects.select_for_update().get(pk=session.pk)
        if s.status not in allowed:
            raise SessionError(message)
        _settle_gap(s, now)
        cur = _current(s)
        _confirm_pending(cur, State.AWAY)  # 휴식·종료 버튼 = 복귀 확인 없이 끝남
        if new_state:
            state, source = _entry(s.mode) if new_state == "ENTRY" else (new_state, Source.MANUAL)
            _switch(s, cur, state, now, source)
        elif cur:
            cur.ended_at = now
            cur.save(update_fields=["ended_at"])
        _reset_candidates(s)
        s.status, s.last_seen_at = new_status, now
        if new_status == Status.ENDED:
            s.ended_at = now
        s.save()
    return s


def pause(session):
    return _change(session, {Status.ACTIVE}, Status.PAUSED, "공부 중일 때만 휴식할 수 있습니다.", State.BREAK)


def resume(session):
    return _change(session, {Status.PAUSED}, Status.ACTIVE, "휴식 중일 때만 재개할 수 있습니다.", "ENTRY")


def end(session):
    return _change(session, {Status.ACTIVE, Status.PAUSED}, Status.ENDED, "이미 종료된 세션입니다.")


def set_mode(session, mode, roi=None, phone_detection=None):
    """수동 ↔ AI 전환 (카메라 켜기/끄기). 공부 중이면 지금부터 새 모드의 진입 구간을 연다."""
    now = timezone.now()
    with transaction.atomic():
        s = _locked(session)
        if roi is not None:
            s.roi = roi
        if phone_detection is not None:
            s.phone_detection = phone_detection
        if s.mode != mode:
            _settle_gap(s, now)
            s.mode = mode
            _reset_candidates(s)
            s.last_observed_at, s.realtime_state = None, {}
            if s.status == Status.ACTIVE:
                state, source = _entry(mode)
                cur = _current(s)
                _confirm_pending(cur, State.AWAY)
                _switch(s, cur, state, now, source)
        s.last_seen_at = now
        s.save()
    return s


def heartbeat(session):
    """화면이 열려 있다는 신호. 수동 모드에서만 끊김(UNKNOWN) 뒤 공부로 복구한다."""
    now = timezone.now()
    with transaction.atomic():
        s = _locked(session)
        _settle_gap(s, now)
        cur = _current(s)
        if s.mode == Mode.MANUAL and s.status == Status.ACTIVE and cur and cur.state == State.UNKNOWN:
            _switch(s, cur, State.STUDY, now, Source.MANUAL)
        s.last_seen_at = now
        s.save()
    return s


PRESENT, ABSENT, UNCLEAR = "present", "absent", "unclear"


def classify(frame_result):
    """FastAPI 프레임 결과 → 관측 종류. 가림·다중 인물·낮은 관절 품질은 UNCLEAR."""
    if frame_result.get("presence_candidate"):
        return PRESENT
    if frame_result.get("quality_passed") and frame_result.get("track_count") == 0:
        return ABSENT
    return UNCLEAR


def observe(session, seq, kind, phone_confidence=None):
    """AI 모드 프레임 1장의 관측 반영. 반환: (세션, 알림 여부, 무시 여부).

    seq가 이미 반영한 번호 이하면(중복·역순·늦은 응답) 아무것도 바꾸지 않는다.
    """
    now = timezone.now()
    alert = False
    with transaction.atomic():
        s = _locked(session)
        if s.mode != Mode.AI:
            raise SessionError("카메라(AI) 모드에서만 프레임을 반영합니다.")
        if seq <= s.last_seq:
            return s, False, True
        s.last_seq = seq
        _settle_gap(s, now)
        cur = _current(s)
        if s.status == Status.ACTIVE and cur:
            if kind == PRESENT:
                s.absent_since, s.last_observed_at = None, now
                s.presence_since = s.presence_since or now
                if cur.state != State.STUDY and now - s.presence_since >= PRESENT_AFTER:
                    back = max(cur.started_at, s.presence_since)  # 첫 복귀 관측 시각 기준
                    _confirm_pending(cur, State.BREAK if back - cur.started_at <= BREAK_LIMIT else State.AWAY)
                    _switch(s, cur, State.STUDY, back, Source.AUTO)
            elif kind == ABSENT:
                s.presence_since, s.last_observed_at = None, now
                s.absent_since = s.absent_since or now
                if cur.state in (State.STUDY, State.UNKNOWN) and now - s.absent_since >= AWAY_AFTER:
                    _switch(s, cur, State.AWAY_PENDING, max(cur.started_at, s.absent_since), Source.AUTO)
                elif cur.state == State.AWAY_PENDING and now - cur.started_at > BREAK_LIMIT:
                    _confirm_pending(cur, State.AWAY)  # 15분이 지나도록 복귀 없음
            else:  # 유효 관측 아님 → last_observed_at 그대로 (timeout 지나면 UNKNOWN)
                _reset_candidates(s)
        else:
            _reset_candidates(s)
        if phone_confidence is not None and s.status == Status.ACTIVE:
            s.phone_since = s.phone_since or now
            if now - s.phone_since >= PHONE_ALERT_AFTER:
                _, alert = BehaviorEvent.objects.get_or_create(
                    dedup_key=f"phone:{s.pk}:{s.phone_since.isoformat()}",
                    defaults={"user": s.user, "session": s, "action_label": "cell_phone",
                              "event_type": BehaviorEvent.EventType.PHONE, "confidence": phone_confidence,
                              "occurred_at": s.phone_since, "source": BehaviorEvent.Source.FOCUS},
                )
        else:
            s.phone_since = None
        s.last_seen_at = now
        s.save()
    return s, alert, False


# ---- 집계 ----

def _segments(interval, now):
    """구간 → (상태, 시작, 끝) 목록. 정산 규칙상 끊긴 부분은 UNKNOWN."""
    if interval.ended_at:
        return [(interval.state, interval.started_at, interval.ended_at)]
    cut = _stale_cut(interval.session, interval, now)
    if cut:
        state = State.AWAY if interval.state == State.AWAY_PENDING else interval.state  # 끊긴 pending = AWAY
        return [(state, interval.started_at, cut), (State.UNKNOWN, cut, now)]
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


def study_seconds_by_source(intervals, now=None):
    """공부 시간을 AI 추정(AUTO)과 수동 기록(MANUAL)으로 나눔."""
    now = now or timezone.now()
    totals = dict.fromkeys(Source.values, 0)
    for iv in intervals:
        for state, a, b in _segments(iv, now):
            if state == State.STUDY:
                totals[iv.source] += int((b - a).total_seconds())
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
