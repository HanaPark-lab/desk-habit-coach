from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import page_views, views

router = DefaultRouter()
router.register("analyses", views.AnalysisJobViewSet, basename="analysis")

urlpatterns = [
    path("api/", include(router.urls)),
    path("analyses/", page_views.job_list, name="analyses_list"),
    path("analyses/new/", page_views.job_new, name="analyses_new"),
    path("analyses/<uuid:pk>/", page_views.job_detail, name="analyses_detail"),
    path("analyses/cameras/<str:key>/stream/", page_views.camera_stream, name="camera_stream"),
]
