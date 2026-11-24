"""Staff usage statistics from account, activity, and service records."""
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from analyses.models import AnalysisJob
from study.models import StudyInterval
from study.services.time_engine import segments_between

from .activity import SEOUL
from .models import DailyUserActivity


def _midnight(day):
    return datetime.combine(day, time.min, tzinfo=SEOUL)


def _study_usage(first, today, now):
    """Keep the study engine's gap handling and split elapsed time at Seoul midnight."""
    start = _midnight(first)
    users_by_day = defaultdict(set)
    today_seconds = defaultdict(lambda: dict.fromkeys(StudyInterval.Source.values, 0))
    intervals = (
        StudyInterval.objects.select_related("session")
        .filter(state=StudyInterval.State.STUDY, started_at__lt=now)
        .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=start))
        .order_by()
    )
    for interval in intervals.iterator():
        for state, began, ended in segments_between((interval,), start, now, now):
            if state != StudyInterval.State.STUDY:
                continue
            day = timezone.localdate(began, SEOUL)
            while began < ended:
                boundary = min(ended, _midnight(day + timedelta(days=1)))
                user_id = interval.session.user_id
                seconds = int((boundary - began).total_seconds())
                if seconds:
                    users_by_day[day].add(user_id)
                    if day == today:
                        today_seconds[user_id][interval.source] += seconds
                began = boundary
                day += timedelta(days=1)
    return users_by_day, today_seconds


def staff_usage_context(visits_page, now=None):
    now = now or timezone.now()
    today = timezone.localdate(now, SEOUL)
    first = today - timedelta(days=6)
    start, today_start, end = _midnight(first), _midnight(today), _midnight(today + timedelta(days=1))
    users = get_user_model().objects
    activities = DailyUserActivity.objects

    joined = dict(users.filter(date_joined__gte=start, date_joined__lt=end).order_by()
                  .annotate(day=TruncDate("date_joined", tzinfo=SEOUL)).values_list("day").annotate(total=Count("pk")))
    first_recorded = activities.aggregate(first=Min("day"))["first"]
    counts = {
        row["day"]: row
        for row in activities.filter(day__range=(first, today)).values("day").annotate(
            logins=Count("pk", filter=Q(logged_in=True)),
            visits=Count("pk", filter=Q(last_seen_at__isnull=False)),
        )
    }
    # A latest login in today's range proves a login today even before collection began.
    # Daily flags still count a user whose latest login overwrote the previous day's timestamp.
    logged_in_today = activities.filter(day=today, logged_in=True).values("user_id")
    today_logins = users.filter(
        Q(last_login__gte=today_start, last_login__lt=end) | Q(pk__in=logged_in_today),
    ).count()
    users_by_day, today_seconds = _study_usage(first, today, now)
    today_jobs = {}
    jobs = (
        AnalysisJob.objects.filter(created_at__gte=start, created_at__lt=end).order_by()
        .annotate(day=TruncDate("created_at", tzinfo=SEOUL)).values("day", "user_id").annotate(total=Count("pk"))
    )
    for job in jobs:
        users_by_day[job["day"]].add(job["user_id"])
        if job["day"] == today:
            today_jobs[job["user_id"]] = job["total"]

    trend = []
    for offset in range(7):
        day = first + timedelta(days=offset)
        daily = counts.get(day, {})
        trend.append({
            "label": f"{day:%m/%d}",
            "joined": joined.get(day, 0),
            "logins": today_logins if day == today else _observed_count(day, first_recorded, daily.get("logins", 0)),
            "visits": daily.get("visits", 0) if day == today else _observed_count(day, first_recorded, daily.get("visits", 0)),
            "used": len(users_by_day[day]),
        })

    latest_users = list(users.order_by("-date_joined", "-pk")[:20])
    visits = activities.filter(day=today, last_seen_at__isnull=False).select_related("user").order_by("-last_seen_at", "user_id")
    page = Paginator(visits, 20).get_page(visits_page)
    visitors = [activity.user for activity in page]
    ids = {user.pk for user in latest_users + visitors}
    last_seen = dict(activities.filter(user_id__in=ids, last_seen_at__isnull=False)
                     .values_list("user_id").annotate(latest=Max("last_seen_at")))

    def detail(user):
        seconds = today_seconds[user.pk]
        return {
            "username": user.get_username(), "joined_at": user.date_joined, "last_seen_at": last_seen.get(user.pk),
            "auto_time": str(timedelta(seconds=seconds[StudyInterval.Source.AUTO])),
            "manual_time": str(timedelta(seconds=seconds[StudyInterval.Source.MANUAL])),
            "job_count": today_jobs.get(user.pk, 0),
        }

    return {
        "total_users": users.count(),
        "today": trend[-1],
        "trend": trend,
        "recent_users": [detail(user) for user in latest_users],
        "visitor_rows": [detail(user) for user in visitors],
        "visits_page": page,
    }


def _observed_count(day, first_observed, count):
    return count if first_observed and day >= first_observed else None
