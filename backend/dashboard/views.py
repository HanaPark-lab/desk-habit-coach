"""대시보드 (UI_UX.md): 오늘 /dashboard/ · 기록 /reports/ · 관리자 /staff/dashboard/ + 집계 API.

모든 숫자는 요청할 때마다 PostgreSQL에서 ORM으로 집계한다 (예시 데이터 없음).
"""
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from analyses.habits import ACTION_NAMES, EVENT_LABELS, behavior_name
from analyses.models import AnalysisJob, PersonPrediction
from study.models import BehaviorEvent, StudyInterval
from study.services.time_engine import current_state, day_range, day_seconds, intervals_between, open_session, seconds_by_state, segments_between

from .usage import staff_usage_context

EventType = BehaviorEvent.EventType
State = StudyInterval.State
STATUS_ORDER = ["SUCCESS", "FAILURE", "STARTED", "PENDING"]
# 색각 이상 검사를 통과한 조합 (초록·보라·황색) + 대기는 회색. 상태 이름이 항상 함께 표시됨
STATUS_COLORS = {"SUCCESS": "#1d7a52", "FAILURE": "#8a4fb8", "STARTED": "#dca23a", "PENDING": "#a7aba3"}
STATE_COLORS = {"STUDY": "#315d49", "BREAK": "#d7bb85", "AWAY": "#9b8fc4", "AWAY_PENDING": "#c4bde0", "UNKNOWN": "#c9ccc4"}
ACTION_LABELS = ("drink_return", "wave", "walk_turn_walk")  # 행동 횟수는 실제 모델 라벨별로 집계


def _day_summary(user, day, now=None):
    start, end = day_range(day)
    valid = BehaviorEvent.objects.filter(user=user, is_valid=True, occurred_at__gte=start, occurred_at__lt=end)
    counts = dict(valid.values_list("event_type").annotate(n=Count("id")))
    actions = dict(valid.values_list("action_label").annotate(n=Count("id")))
    return {
        "date": day,
        "seconds": day_seconds(user, day, now),
        "events": {e: counts.get(e, 0) for e in EventType.values},
        "actions": {a: actions.get(a, 0) for a in ACTION_LABELS},
    }


def _week(user, today):
    return [_day_summary(user, today - timedelta(days=i)) for i in range(6, -1, -1)]


WEEKDAYS = "월화수목금토일"
FEED_TEXT = {"STUDY": "공부 시작·재개", "BREAK": "휴식", "AWAY": "장기 자리 비움", "AWAY_PENDING": "자리 비움 · 복귀 확인 중",
             "UNKNOWN": "카메라 확인 필요 (확인 불가)"}


def _timeline(user, day, now):
    """오늘 상태 구간 → (막대 % 위치, 시간 눈금). 첫 구간 시작 ~ 마지막 구간 끝 기준."""
    start, end = day_range(day)
    segs = segments_between(intervals_between(user, start, end), start, end, now)
    if not segs:
        return [], []
    t0, t1 = segs[0][1], max(b for _, _, b in segs)
    span = (t1 - t0).total_seconds() or 1
    pct = lambda t: round((t - t0).total_seconds() / span * 100, 2)  # noqa: E731
    bars = [{
        "label": State(s).label, "color": STATE_COLORS[s], "left": pct(a),
        "width": max(0.4, round((b - a).total_seconds() / span * 100, 2)),
        "start": timezone.localtime(a), "end": timezone.localtime(b),
    } for s, a, b in segs]
    local0 = timezone.localtime(t0)
    hours = [local0.replace(minute=0, second=0, microsecond=0) + timedelta(hours=h) for h in range(1, 25)]
    ticks = [{"left": 0, "text": f"{local0:%H:%M}"}] + [
        {"left": pct(h), "text": f"{h:%H:00}"} for h in hours if t0 < h < t1 and 8 < pct(h) < 92  # 양 끝 글자 겹침 방지
    ]
    return bars, ticks


def _feed(user, start, end):
    """AI 자동 기록: 행동 기록 + 공부 세션 상태 변화, 최근 순."""
    items = [{"kind": e.event_type, "text": f"{behavior_name(e)} 감지" + ("" if e.is_valid else " (정정됨)"), "at": e.occurred_at}
             for e in BehaviorEvent.objects.filter(user=user, occurred_at__gte=start, occurred_at__lt=end)]
    items += [{"kind": iv.state, "text": FEED_TEXT[iv.state], "at": iv.started_at}
              for iv in StudyInterval.objects.filter(session__user=user, started_at__gte=start, started_at__lt=end)]
    return sorted(items, key=lambda i: i["at"], reverse=True)[:8]


@login_required
def today(request):
    now = timezone.now()
    day = timezone.localdate(now)
    user = request.user
    summary = _day_summary(user, day, now)
    session = open_session(user)
    start, end = day_range(day)
    goals = settings.DAILY_GOALS
    seconds = summary["seconds"]
    goal_seconds = goals["STUDY_MINUTES"] * 60
    hours, remainder = divmod(seconds[State.STUDY], 3600)
    minutes, clock_seconds = divmod(remainder, 60)
    bars, ticks = _timeline(user, day, now)
    valid_today = BehaviorEvent.objects.filter(user=user, is_valid=True, occurred_at__gte=start, occurred_at__lt=end)
    last = {e: valid_today.filter(event_type=e).values_list("occurred_at", flat=True).first() for e in (EventType.DRINK, EventType.MOVEMENT)}
    monday = day - timedelta(days=day.weekday())  # 이번 주 월~일
    week = []
    for index, label in enumerate(WEEKDAYS):
        date = monday + timedelta(days=index)
        study_seconds = seconds[State.STUDY] if date == day else 0
        if date < day:
            study_seconds = day_seconds(user, date, now)[State.STUDY]
        week.append({"label": label, "today": date == day, "seconds": study_seconds, "duration": _duration(study_seconds)})
    return render(request, "dashboard/today.html", {
        "summary": summary,
        "goals": goals,
        "goal_hours": f"{goals['STUDY_MINUTES'] / 60:g}",
        "goal_pct": min(100, round(seconds[State.STUDY] / goal_seconds * 100)) if goal_seconds > 0 else 0,
        "goal_seconds": goal_seconds,
        "study_clock": f"{hours:02d}:{minutes:02d}:{clock_seconds:02d}",
        "break_duration": _duration(seconds[State.BREAK]),
        "away_duration": _duration(seconds[State.AWAY]),
        "pending_duration": _duration(seconds[State.AWAY_PENDING]),
        "unknown_duration": _duration(seconds[State.UNKNOWN]),
        "session": session,
        "running": bool(session and session.mode == "MANUAL" and current_state(session, now)[0] == State.STUDY),
        "timeline": bars,
        "ticks": ticks,
        "feed": _feed(user, start, end),
        "last": last,
        "drops": [i < summary["events"]["DRINK"] for i in range(goals["DRINK"])],
        "move_pct": min(100, round(summary["events"]["MOVEMENT"] / goals["MOVEMENT"] * 100)) if goals["MOVEMENT"] else 0,
        "week_data": week,
        "has_week_study": any(entry["seconds"] for entry in week),
    })


def _report_buckets(first_day, size, count, intervals, event_counts, now):
    auto_study = [iv for iv in intervals if iv.state == State.STUDY and iv.source == StudyInterval.Source.AUTO]
    for index in range(count):
        first = first_day + timedelta(days=index * size)
        last = first + timedelta(days=size - 1)
        start, _ = day_range(first)
        _, end = day_range(last)
        end = min(end, now)
        seconds = seconds_by_state(intervals, start, end, now)
        auto = seconds_by_state(auto_study, start, end, now)[State.STUDY]
        counts = Counter()
        for offset in range(size):
            counts.update(event_counts.get(first + timedelta(days=offset), {}))
        yield {
            "label": f"{first:%m/%d}" if size == 1 else f"{first:%m/%d}–{last:%m/%d}",
            "auto": auto,
            "manual": seconds[State.STUDY] - auto,
            "break": seconds[State.BREAK],
            "away": seconds[State.AWAY] + seconds[State.AWAY_PENDING],
            "unknown": seconds[State.UNKNOWN],
            "drink": counts[EventType.DRINK],
            "movement": counts[EventType.MOVEMENT],
            "wave": counts["wave"],
            "walk": counts["walk_turn_walk"],
        }


def _duration(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, remainder = divmod(remainder, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분" if minutes or not remainder else f"{remainder}초"


@login_required
def reports(request):
    now = timezone.now()
    day = timezone.localdate(now)
    period = "4w" if request.GET.get("period") == "4w" else "7d"
    size, count = (7, 4) if period == "4w" else (1, 7)
    first = day - timedelta(days=size * count - 1)
    start, _ = day_range(first)
    _, end = day_range(day)
    events = BehaviorEvent.objects.filter(user=request.user, occurred_at__gte=start, occurred_at__lt=end)
    event_counts = {}
    rows = (events.filter(is_valid=True).order_by().annotate(day=TruncDate("occurred_at"))
            .values("day", "event_type", "action_label").annotate(total=Count("id")))
    for row in rows:
        counts = event_counts.setdefault(row["day"], Counter())
        counts[row["event_type"]] += row["total"]
        if row["event_type"] == EventType.MOVEMENT and row["action_label"] in ("wave", "walk_turn_walk"):
            counts[row["action_label"]] += row["total"]

    intervals = list(intervals_between(request.user, start, end))
    buckets = list(_report_buckets(first, size, count, intervals, event_counts, now))
    totals = {key: sum(bucket[key] for bucket in buckets) for key in buckets[0] if key != "label"}
    time_total = sum(totals[key] for key in ("auto", "manual", "break", "away", "unknown"))
    drink_goal = settings.DAILY_GOALS["DRINK"] * size
    charts = [
        {"id": "time-trend", "title": "시간 추이", "detail": "자리 비움에는 복귀 확인 중인 시간이 포함됩니다.", "has_data": time_total},
        {"id": "time-share", "title": "시간 사용 비율", "has_data": time_total},
        {"id": "drink-trend", "title": "음료 섭취", "detail": f"{'주간' if size == 7 else '일간'} 목표 {drink_goal}회", "has_data": totals["drink"]},
        {"id": "movement-trend", "title": "휴식 활동", "has_data": totals["wave"] + totals["walk"]},
    ]
    jobs = request.user.analysis_jobs.filter(created_at__gte=start, created_at__lt=end).prefetch_related("predictions")
    return render(request, "dashboard/reports.html", {
        "period": period, "first": first, "today": day, "charts": charts, "jobs": jobs,
        "events": events.select_related("job"),
        "summary": {
            "study": _duration(totals["auto"] + totals["manual"]),
            "break": _duration(totals["break"]),
            "drink": totals["drink"],
            "movement": totals["movement"],
        },
        "chart_data": {"buckets": buckets, "totals": totals, "drinkGoal": drink_goal},
    })


@api_view(["GET"])
def today_api(request):
    """GET /api/dashboard/today/ — 오늘 상태별 시간(초)·유효 행동 횟수·목표."""
    summary = _day_summary(request.user, timezone.localdate())
    return Response({**summary, "timezone": settings.TIME_ZONE, "goals": settings.DAILY_GOALS})


@api_view(["GET"])
def weekly_api(request):
    """GET /api/dashboard/weekly/ — 최근 7일."""
    return Response({"timezone": settings.TIME_ZONE, "days": _week(request.user, timezone.localdate())})


def _rate(part, whole):
    return round(part / whole * 100, 1) if whole else None


@login_required
def staff_dashboard(request):
    """관리자 전용 (교과 필수 차트 2개: 동작별 예측 건수 막대, 작업 상태별 건수 원형)."""
    if not request.user.is_staff:
        raise PermissionDenied  # 일반 회원은 403

    usage = staff_usage_context(request.GET.get("visits_page"))
    jobs = AnalysisJob.objects.all()
    status_counts = dict(jobs.values_list("status").annotate(n=Count("id")))
    success, failure = status_counts.get("SUCCESS", 0), status_counts.get("FAILURE", 0)
    recorded = jobs.filter(events__isnull=False).distinct().count()
    avg_ms = jobs.filter(status=AnalysisJob.Status.SUCCESS).aggregate(a=Avg("processing_ms"))["a"]

    action_counts = dict(PersonPrediction.objects.values_list("action_label").annotate(n=Count("id")))
    labels = [label for group in EVENT_LABELS.values() for label in group] + ["other"]
    labels += sorted(set(action_counts) - set(labels))  # 모델이 바뀌어 새 라벨이 생겨도 빠뜨리지 않음
    top = max(action_counts.values(), default=0) or 1
    actions = [{"label": l, "name": ACTION_NAMES.get(l, l), "count": action_counts.get(l, 0),
                "pct": round(action_counts.get(l, 0) / top * 100)} for l in labels]
    statuses = [
        {"status": s, "label": AnalysisJob.Status(s).label, "count": status_counts.get(s, 0), "color": STATUS_COLORS[s]}
        for s in STATUS_ORDER
    ]
    stats = {
        "users": usage["total_users"],
        "total": sum(status_counts.values()),
        "success": success,
        "failure": failure,
        "success_rate": _rate(success, success + failure),  # 분석 처리 성공률
        "record_rate": _rate(recorded, success),            # 완료 작업 중 행동이 기록된 비율
        "avg_seconds": round(avg_ms / 1000, 1) if avg_ms is not None else None,
        "recorded": recorded,
        "not_recorded": success - recorded,
    }
    # 분석 결과 분포 (원형): 완료를 '기록됨/기록 안 함'으로 나눈 작업 상태별 건수
    segments = [
        {"label": "기록됨", "status": "SUCCESS", "count": recorded, "color": STATUS_COLORS["SUCCESS"]},
        {"label": "기록 안 함", "status": "SUCCESS", "count": success - recorded, "color": STATUS_COLORS["STARTED"]},
        {"label": "실패", "status": "FAILURE", "count": failure, "color": STATUS_COLORS["FAILURE"]},
        {"label": "대기·분석 중", "status": "PENDING·STARTED",
         "count": status_counts.get("PENDING", 0) + status_counts.get("STARTED", 0), "color": STATUS_COLORS["PENDING"]},
    ]
    recent = []
    for job in jobs.select_related("user").prefetch_related("predictions", "events")[:20]:
        prediction = next(iter(job.predictions.all()), None)
        label = prediction.action_label if prediction else "-"
        recent.append({"job": job, "short_id": str(job.pk)[:8], "action": ACTION_NAMES.get(label, label)})
    return render(request, "dashboard/staff.html", {
        "stats": stats, "actions": actions, "statuses": statuses, "segments": segments, "recent": recent,
        "usage": usage,
        "chart_data": {"segments": segments, "usageTrend": usage["trend"]},
    })
