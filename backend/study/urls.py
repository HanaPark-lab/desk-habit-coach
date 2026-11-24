from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("study/sessions", views.StudySessionViewSet, basename="study-session")
router.register("study/events", views.BehaviorEventViewSet, basename="study-event")

urlpatterns = [
    path("api/", include(router.urls)),
    path("study/", views.session_page, name="study"),
]
