from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("api-auth/", include("rest_framework.urls")),  # DRF 화면 오른쪽 위 로그인·로그아웃 링크
    path("", include("analyses.urls")),   # /api/analyses/..., /analyses/, /analyses/new/, /analyses/<id>/
    path("", include("study.urls")),      # /api/study/..., /study/
    path("", include("dashboard.urls")),  # /dashboard/, /reports/, /staff/dashboard/, /api/dashboard/...
    path("", RedirectView.as_view(pattern_name="today")),
]
