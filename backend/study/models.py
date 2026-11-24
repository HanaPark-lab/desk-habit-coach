import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class StudySession(models.Model):
    """공부 세션 1회. 사용자당 열린(ACTIVE·PAUSED) 세션은 하나만."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "공부 중"
        PAUSED = "PAUSED", "휴식 중"
        ENDED = "ENDED", "종료"

    class Mode(models.TextChoices):
        MANUAL = "MANUAL", "수동 타이머"   # 버튼·heartbeat 기준. AI가 확인한 시간이 아님
        AI = "AI", "AI 착석 추정"        # 카메라 관측 기준

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="study_sessions")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.MANUAL)
    roi = models.JSONField(null=True, blank=True, help_text="AI 모드 착석 영역 [x1, y1, x2, y2] (0~1). 비우면 화면 전체")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, help_text="수동 모드: 마지막 heartbeat. 끊긴 뒤 시간은 UNKNOWN으로 정산")
    last_seq = models.BigIntegerField(default=0, help_text="AI 모드: 마지막으로 반영한 프레임 번호 (중복·역순 무시)")
    last_observed_at = models.DateTimeField(null=True, blank=True, help_text="AI 모드: 마지막 유효 관측(사람 있음/없음이 분명한 프레임) 시각")
    presence_since = models.DateTimeField(null=True, blank=True, help_text="AI 모드: 복귀 후보 시작 시각")
    absent_since = models.DateTimeField(null=True, blank=True, help_text="AI 모드: 부재 후보 시작 시각")
    realtime_state = models.JSONField(default=dict, blank=True, help_text="AI 모드 실시간 행동: 진행 중 episode·유형별 마지막 기록 시각")
    phone_detection = models.BooleanField(default=False, help_text="선택 기능: 휴대폰 감지 (순공시간에서 차감하지 않음)")
    phone_since = models.DateTimeField(null=True, blank=True, help_text="집중 모드: 휴대폰이 연속으로 보이기 시작한 시각")

    class Meta:
        ordering = ["-started_at"]
        constraints = [models.UniqueConstraint(
            fields=["user"], condition=~Q(status="ENDED"), name="one_open_session_per_user",
        )]
        verbose_name = verbose_name_plural = "공부 세션"

    def __str__(self):
        return f"{self.user} · {self.get_status_display()} · {timezone.localtime(self.started_at):%m-%d %H:%M}"


class StudyInterval(models.Model):
    """세션 안의 상태 구간 [started_at, ended_at). 세션당 열린 구간은 하나, 구간끼리 겹치지 않음."""

    class State(models.TextChoices):
        STUDY = "STUDY", "공부"
        BREAK = "BREAK", "휴식"
        AWAY = "AWAY", "자리 비움"             # 15분 넘게 비움 (또는 복귀 확인 없이 끝남)
        AWAY_PENDING = "AWAY_PENDING", "복귀 확인 중"  # 이탈 중. 복귀 시각에 따라 BREAK/AWAY로 확정
        UNKNOWN = "UNKNOWN", "확인 불가"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "버튼"
        AUTO = "AUTO", "자동 감지"

    session = models.ForeignKey(StudySession, on_delete=models.CASCADE, related_name="intervals")
    state = models.CharField(max_length=15, choices=State.choices)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)

    class Meta:
        ordering = ["started_at"]
        constraints = [models.UniqueConstraint(
            fields=["session"], condition=Q(ended_at__isnull=True), name="one_open_interval_per_session",
        )]
        verbose_name = verbose_name_plural = "상태 구간"


class BehaviorEvent(models.Model):
    """AI가 인식한 행동 1건 (음료·움직임·휴대폰). 클립 작업 1건당 최대 1건, 실시간은 episode당 1건 (dedup_key)."""

    class EventType(models.TextChoices):
        DRINK = "DRINK", "음료 섭취"
        MOVEMENT = "MOVEMENT", "스트레칭·움직임"
        PHONE = "PHONE", "집중 이탈(휴대폰)"  # 집중 모드에서 휴대폰이 일정 시간 계속 보임

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="behavior_events")
    session = models.ForeignKey(StudySession, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    job = models.ForeignKey("analyses.AnalysisJob", null=True, blank=True, on_delete=models.CASCADE, related_name="events")
    class Source(models.TextChoices):
        CLIP = "CLIP", "클립 분석"
        REALTIME = "REALTIME", "실시간 분석"
        FOCUS = "FOCUS", "집중 모드(휴대폰)"

    action_label = models.CharField(max_length=50, help_text="실제 모델 라벨")
    event_type = models.CharField(max_length=10, choices=EventType.choices)
    confidence = models.FloatField(help_text="모델 점수. 정확도가 아님")
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.CLIP)
    model_version = models.CharField(max_length=50, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    dedup_key = models.CharField(max_length=100, unique=True)
    is_valid = models.BooleanField(default=True, help_text="사용자가 오인식으로 정정하면 False (집계 제외)")

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = verbose_name_plural = "행동 기록"

    def __str__(self):
        return f"{self.get_event_type_display()} · {timezone.localtime(self.occurred_at):%m-%d %H:%M}"
