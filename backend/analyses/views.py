import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from study.services.time_engine import open_session

from .models import AnalysisJob
from .serializers import AnalysisJobSerializer
from .tasks import analyze_job, fail_stale_jobs

logger = logging.getLogger(__name__)

STATUS_FIELDS = (
    "id", "status", "input_type", "session", "model_profile", "model_version", "error_code",
    "error_message", "processing_ms", "created_at", "finished_at", "predictions", "record",
)


def enqueue(job):
    try:
        analyze_job.delay(str(job.pk))
    except Exception:  # Redis가 꺼져 있어도 작업이 영원히 PENDING으로 남지 않게
        logger.exception("job %s: 큐 등록 실패", job.pk)
        AnalysisJob.objects.filter(pk=job.pk).update(
            status=AnalysisJob.Status.FAILURE, error_code="QUEUE_ERROR",
            error_message="작업 대기열에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.", finished_at=timezone.now(),
        )


class AnalysisJobViewSet(viewsets.ModelViewSet):
    """내 분석 작업 CRUD. 다른 사용자의 작업은 목록에도 없고 상세는 404."""

    serializer_class = AnalysisJobSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]  # PUT 금지

    def get_queryset(self):
        return AnalysisJob.objects.filter(user=self.request.user).prefetch_related("predictions", "events")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # 진행 중인 공부 세션이 있으면 연결 (결과 행동 기록이 그 세션에 들어감)
        job = serializer.save(user=request.user, session=open_session(request.user))
        if job.video_file and Path(job.video_file.name).suffix.lower() not in settings.ALLOWED_VIDEO_EXTENSIONS:
            # T09: 잘못된 파일도 작업을 먼저 만들고 FAILURE로 기록 (AI 서버로 보내지 않음)
            job.video_file.delete(save=False)
            job.status = AnalysisJob.Status.FAILURE
            job.error_code = "INVALID_FILE"
            job.error_message = "MP4 등 영상 파일만 분석할 수 있습니다."
            job.finished_at = timezone.now()
            job.save()
        else:
            # DB 저장이 확정된 뒤에 큐 등록 (Worker가 아직 없는 작업을 찾는 일 방지)
            transaction.on_commit(lambda: enqueue(job))
        job.refresh_from_db()
        return Response(self.get_serializer(job).data, status=202)

    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        if job.status in (AnalysisJob.Status.PENDING, AnalysisJob.Status.STARTED):
            return Response({"detail": "분석 중인 작업은 끝난 뒤에 삭제할 수 있습니다."}, status=409)
        storage, name = job.video_file.storage, job.video_file.name
        with transaction.atomic():
            job.delete()  # PersonPrediction·BehaviorEvent는 CASCADE로 함께 삭제
            if name:  # DB 삭제가 확정된 뒤에 파일 삭제 (롤백되면 파일은 남음)
                transaction.on_commit(lambda: storage.delete(name))
        return Response(status=204)

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        fail_stale_jobs()  # Worker가 죽어 STARTED로 남은 작업 정리
        data = self.get_serializer(self.get_object()).data
        return Response({k: data[k] for k in STATUS_FIELDS})
