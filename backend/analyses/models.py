import uuid

from django.conf import settings
from django.db import models


class AnalysisJob(models.Model):
    """클립 분석 요청 1건 (영상 업로드 또는 IP Webcam). 상태는 서버(Worker)만 바꾼다."""

    class InputType(models.TextChoices):
        UPLOAD = "UPLOAD", "영상 업로드"
        IPCAM = "IPCAM", "IP Webcam"

    class Status(models.TextChoices):
        PENDING = "PENDING", "대기"
        STARTED = "STARTED", "분석 중"
        SUCCESS = "SUCCESS", "완료"
        FAILURE = "FAILURE", "실패"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 순번 추측 방지
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="analysis_jobs")
    session = models.ForeignKey(
        "study.StudySession", null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs",
        help_text="분석 요청 당시 진행 중이던 공부 세션 (없으면 비움)",
    )
    title = models.CharField(max_length=150, blank=True)
    memo = models.TextField(blank=True)
    input_type = models.CharField(max_length=10, choices=InputType.choices)
    video_file = models.FileField(upload_to="videos/%Y/%m/%d/", blank=True)  # 파일은 Media, DB에는 경로만
    camera_key = models.CharField(max_length=50, blank=True)  # 허용 카메라 별칭. URL은 저장하지 않음
    capture_seconds = models.PositiveSmallIntegerField(default=8)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    model_version = models.CharField(max_length=50, blank=True)
    error_code = models.CharField(max_length=50, blank=True)
    error_message = models.TextField(blank=True)
    processing_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = verbose_name_plural = "분석 작업"

    def __str__(self):
        return f"{self.get_input_type_display()} · {self.status} · {self.created_at:%m-%d %H:%M}"


class PersonPrediction(models.Model):
    """작업 1건 안의 사람 1명의 대표 예측."""

    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name="predictions")
    track_id = models.PositiveIntegerField(help_text="영상 안의 추적 번호. 영구적인 사람 ID가 아님")
    action_label = models.CharField(max_length=50)
    confidence = models.FloatField(help_text="모델 점수(predict_proba 최댓값). 정확도가 아님")
    window_count = models.PositiveIntegerField()
    probabilities = models.JSONField(default=dict)
    predicted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["job", "track_id"]
        constraints = [models.UniqueConstraint(fields=["job", "track_id"], name="unique_track_per_job")]
        verbose_name = verbose_name_plural = "사람별 예측"

    def __str__(self):
        return f"#{self.track_id} {self.action_label} {self.confidence:.2f}"
