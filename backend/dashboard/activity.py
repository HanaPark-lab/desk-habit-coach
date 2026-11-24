from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from .models import DailyUserActivity

SEOUL = ZoneInfo("Asia/Seoul")

# User-facing pages and deliberate actions. Background frames, polling and heartbeats are excluded.
TRACKED_VIEWS = {
    "today", "study", "analyses_list", "analyses_detail", "reports",
    "analysis-list", "analysis-detail",
    "study-session-list", "study-session-detail",
    "study-session-mode", "study-session-pause", "study-session-resume", "study-session-end",
    "study-event-list", "study-event-detail",
}


def record_login(sender, request, user, **kwargs):
    now = timezone.now()
    activity, _ = DailyUserActivity.objects.get_or_create(
        user=user, day=timezone.localdate(now, SEOUL), defaults={"logged_in": True},
    )
    if not activity.logged_in:
        DailyUserActivity.objects.filter(pk=activity.pk).update(logged_in=True)


class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        now = timezone.now()
        response = self.get_response(request)
        match = request.resolver_match
        if 200 <= response.status_code < 300 and match and match.view_name in TRACKED_VIEWS and request.user.is_authenticated:
            activity, created = DailyUserActivity.objects.get_or_create(
                user=request.user, day=timezone.localdate(now, SEOUL), defaults={"last_seen_at": now},
            )
            if not created:
                # Do not let a slower concurrent request move the timestamp backwards.
                DailyUserActivity.objects.filter(pk=activity.pk).filter(
                    Q(last_seen_at__lt=now) | Q(last_seen_at__isnull=True),
                ).update(last_seen_at=now)
        return response
