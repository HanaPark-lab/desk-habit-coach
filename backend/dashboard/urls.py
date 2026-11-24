from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.today, name="today"),
    path("reports/", views.reports, name="reports"),
    path("staff/dashboard/", views.staff_dashboard, name="staff_dashboard"),
    path("api/dashboard/today/", views.today_api, name="dashboard_today"),
    path("api/dashboard/weekly/", views.weekly_api, name="dashboard_weekly"),
]
