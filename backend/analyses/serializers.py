from django.conf import settings
from django.urls import reverse
from rest_framework import serializers

from study.models import BehaviorEvent

from .habits import OTHER_LABEL, top_event
from .models import AnalysisJob, PersonPrediction

EVENT_NAMES = dict(BehaviorEvent.EventType.choices)


class PersonPredictionSerializer(serializers.ModelSerializer):
    event_type = serializers.SerializerMethodField()   # "" = 기타 동작
    event_score = serializers.SerializerMethodField()

    class Meta:
        model = PersonPrediction
        fields = ["track_id", "action_label", "confidence", "window_count", "probabilities", "event_type", "event_score"]

    def get_event_type(self, obj):
        return "" if obj.action_label == OTHER_LABEL else top_event(obj.probabilities)[0]

    def get_event_score(self, obj):
        score = obj.confidence if obj.action_label == OTHER_LABEL else top_event(obj.probabilities)[1]
        return round(score, 4)


class AnalysisJobSerializer(serializers.ModelSerializer):
    predictions = PersonPredictionSerializer(many=True, read_only=True)
    status_url = serializers.SerializerMethodField()
    record = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisJob
        fields = [
            "id", "title", "memo", "input_type", "video_file", "camera_key", "capture_seconds", "session",
            "status", "status_url", "model_version", "error_code", "error_message", "processing_ms",
            "created_at", "finished_at", "predictions", "record",
        ]
        # 상태·AI 결과·세션 연결은 사용자가 바꿀 수 없음 (서버만 변경)
        read_only_fields = [
            "id", "session", "status", "model_version", "error_code", "error_message",
            "processing_ms", "created_at", "finished_at",
        ]
        extra_kwargs = {"video_file": {"write_only": True}}  # 서버 내부 저장 경로는 응답에 노출하지 않음

    def get_status_url(self, obj):
        return reverse("analysis-status", args=[obj.pk])

    def get_record(self, job):
        """행동 기록 여부와 이유. 판정은 서버가 하고 브라우저는 표시만 한다. 진행 중이면 None."""
        if job.status in (AnalysisJob.Status.PENDING, AnalysisJob.Status.STARTED):
            return None
        if job.status == AnalysisJob.Status.FAILURE:
            return {"recorded": False, "event_type": "", "reason": job.error_message or "분석에 실패했습니다."}
        event = next(iter(job.events.all()), None)
        if event:
            note = "" if event.is_valid else " (오인식으로 정정됨)"
            return {"recorded": True, "event_type": event.event_type, "reason": f"{EVENT_NAMES[event.event_type]} 1회 기록{note}"}
        preds = list(job.predictions.all())
        if not preds:
            reason = job.error_message or "분석할 사람을 찾지 못했습니다."
        elif all(p.action_label == OTHER_LABEL for p in preds):
            reason = "학습한 행동이 아닌 동작(기타)으로 인식되어 기록하지 않았습니다."
        else:
            reason = "판단 보류: 점수가 기준보다 낮아 기록하지 않았습니다."
        return {"recorded": False, "event_type": "", "reason": reason}

    def validate_video_file(self, f):
        if f and f.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise serializers.ValidationError(f"{settings.MAX_UPLOAD_MB}MB 이하 영상만 올릴 수 있습니다.")
        return f

    def validate_capture_seconds(self, value):
        if not 5 <= value <= 15:
            raise serializers.ValidationError("수집 시간은 5~15초만 가능합니다.")
        return value

    def validate(self, data):
        if self.instance:  # PATCH: 입력 방식 검사 없음 (update에서 제목·메모만 반영)
            return data
        if data["input_type"] == AnalysisJob.InputType.UPLOAD:
            if not data.get("video_file"):
                raise serializers.ValidationError({"video_file": "영상 파일을 올려 주세요."})
            data["camera_key"] = ""
        else:
            if data.get("camera_key") not in settings.CAMERAS:
                raise serializers.ValidationError({"camera_key": "허용된 카메라가 아닙니다."})
            data.pop("video_file", None)
        return data

    def update(self, instance, validated_data):
        fields = [f for f in ("title", "memo") if f in validated_data]
        for f in fields:
            setattr(instance, f, validated_data[f])
        instance.save(update_fields=fields)
        return instance
