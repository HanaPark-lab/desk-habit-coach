from django.conf import settings
from django.db import models


class DailyUserActivity(models.Model):
    """One row per authenticated user and Seoul calendar day."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_activity")
    day = models.DateField()
    logged_in = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("day", "user"), name="dashboard_activity_day_user_unique"),
        ]
