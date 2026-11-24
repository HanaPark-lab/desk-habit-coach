from django.apps import AppConfig


class DashboardConfig(AppConfig):
    name = "dashboard"
    verbose_name = "대시보드"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .activity import record_login

        user_logged_in.connect(record_login, dispatch_uid="dashboard.record_daily_login")
