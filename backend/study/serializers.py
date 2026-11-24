from rest_framework import serializers

from .models import BehaviorEvent, StudyInterval, StudySession
from .services.time_engine import current_state, seconds_by_state, study_seconds_by_source


class IntervalSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudyInterval
        fields = ["state", "started_at", "ended_at", "source"]


class StudySessionSerializer(serializers.ModelSerializer):
    current_state = serializers.SerializerMethodField()
    current_started_at = serializers.SerializerMethodField()
    seconds = serializers.SerializerMethodField()
    study_seconds_by_source = serializers.SerializerMethodField()
    distractions = serializers.SerializerMethodField()
    intervals = IntervalSerializer(many=True, read_only=True)

    class Meta:
        model = StudySession
        fields = ["id", "status", "mode", "roi", "phone_detection", "started_at", "ended_at", "last_seen_at", "last_seq",
                  "current_state", "current_started_at", "seconds", "study_seconds_by_source", "distractions", "intervals"]
        read_only_fields = fields

    def get_current_state(self, obj):
        """집계와 같은 정산 규칙을 적용한 현재 상태 (끊겼으면 UNKNOWN)."""
        return current_state(obj)[0]

    def get_current_started_at(self, obj):
        """현재 구간 시작 시각 (집중 모드의 '현재 집중 세션'·'다음 휴식까지' 계산용)."""
        return current_state(obj)[1]

    def get_study_seconds_by_source(self, obj):
        """공부 시간 중 AI 추정(AUTO)과 수동 기록(MANUAL)."""
        return study_seconds_by_source(obj.intervals.all())

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
