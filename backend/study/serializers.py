from rest_framework import serializers

from .models import BehaviorEvent, StudyInterval, StudySession
from .services.time_engine import seconds_by_state


class IntervalSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudyInterval
        fields = ["state", "started_at", "ended_at", "source"]


class StudySessionSerializer(serializers.ModelSerializer):
    current_state = serializers.SerializerMethodField()
    current_started_at = serializers.SerializerMethodField()
    seconds = serializers.SerializerMethodField()
    distractions = serializers.SerializerMethodField()
    intervals = IntervalSerializer(many=True, read_only=True)

    class Meta:
        model = StudySession
        fields = ["id", "status", "started_at", "ended_at", "last_seen_at", "current_state", "current_started_at",
                  "seconds", "distractions", "intervals"]
        read_only_fields = fields

    def _open(self, obj):
        return next((i for i in obj.intervals.all() if i.ended_at is None), None)

    def get_current_state(self, obj):
        return getattr(self._open(obj), "state", None)

    def get_current_started_at(self, obj):
        """현재 구간 시작 시각 (집중 모드의 '현재 집중 세션'·'다음 휴식까지' 계산용)."""
        iv = self._open(obj)
        return iv.started_at if iv else None

    def get_distractions(self, obj):
        return obj.events.filter(event_type=BehaviorEvent.EventType.PHONE, is_valid=True).count()

    def get_seconds(self, obj):
        """상태별 누적 초 (STUDY·BREAK·AWAY·UNKNOWN). 열린 구간은 지금까지."""
        return seconds_by_state(obj.intervals.all())


class BehaviorEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = BehaviorEvent
        fields = ["id", "event_type", "action_label", "confidence", "occurred_at", "session", "job", "is_valid"]
        read_only_fields = ["id", "event_type", "action_label", "confidence", "occurred_at", "session", "job"]  # 정정(is_valid)만 수정 가능
