"""Celery 작업: 영상 확보 → FastAPI 추론 → Django ORM으로 결과 저장."""
import logging
import time
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from study.services.event_service import record_from_job

from .camera_capture import capture
from .models import AnalysisJob, PersonPrediction
from .services import AnalysisError, predict_video

logger = logging.getLogger(__name__)
Status = AnalysisJob.Status
RESULT_FIELDS = ("track_id", "action_label", "confidence", "window_count", "probabilities")


@shared_task(bind=True)
def analyze_job(self, job_id):
    """PENDING → STARTED → SUCCESS / FAILURE. 같은 작업이 두 번 와도 한 번만 처리한다."""
    claimed = AnalysisJob.objects.filter(pk=job_id, status=Status.PENDING).update(
        status=Status.STARTED, celery_task_id=self.request.id or ""
    )
    if not claimed:
        logger.info("job %s: PENDING이 아니므로 건너뜀", job_id)
        return
    job = AnalysisJob.objects.get(pk=job_id)
    start = time.monotonic()
    logger.info("job %s: 시작 (%s)", job_id, job.input_type)
    try:
        if job.input_type == AnalysisJob.InputType.IPCAM:
            _capture_into(job)
        result = predict_video(job.video_file.path)
    except AnalysisError as e:
        _finish(job, start, status=Status.FAILURE, error_code=e.code, error_message=e.message)
        return
    except Exception:
        logger.exception("job %s: 예상하지 못한 오류", job_id)
        _finish(job, start, status=Status.FAILURE, error_code="INTERNAL_ERROR", error_message="분석 중 알 수 없는 오류가 발생했습니다.")
        return

    with transaction.atomic():  # 사람별 결과·행동 기록·SUCCESS를 함께 저장
        PersonPrediction.objects.bulk_create(
            PersonPrediction(job=job, **{k: p[k] for k in RESULT_FIELDS}) for p in result["predictions"]
        )
        _finish(
            job, start, status=Status.SUCCESS,
            model_profile=result.get("model_profile", ""),
            model_version=result.get("model_version", ""),
            error_code=result.get("error_code", ""),
            error_message=result.get("message", ""),
        )
        record_from_job(job, result["predictions"])  # 기준 통과 시 BehaviorEvent 1건 (작업당 최대 1건)


def _capture_into(job):
    if not settings.CAMERAS.get(job.camera_key):
        raise AnalysisError("CAMERA_NOT_ALLOWED", "허용되지 않은 카메라입니다.")
    from .page_views import relay_token  # noqa: PLC0415
    # 카메라에 직접 붙지 않고 Django 중계 허브에서 받음 → 미리보기와 동시에 수집 가능 (DroidCam은 1곳만 접속 가능)
    url = f"{settings.CAMERA_RELAY_BASE}/analyses/cameras/{job.camera_key}/stream/?token={relay_token(job.camera_key)}"
    rel = f"videos/ipcam/{job.pk}.mp4"
    out = Path(settings.MEDIA_ROOT) / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    logger.info("job %s: 카메라 %s에서 %s초 수집", job.pk, job.camera_key, job.capture_seconds)
    capture(url, job.capture_seconds, out)
    job.video_file.name = rel
    job.save(update_fields=["video_file"])


def _finish(job, start, **fields):
    for name, value in fields.items():
        setattr(job, name, value)
    job.processing_ms = int((time.monotonic() - start) * 1000)
    job.finished_at = timezone.now()
    job.save()
    logger.info("job %s: %s %s (%d ms)", job.pk, job.status, job.error_code, job.processing_ms)
