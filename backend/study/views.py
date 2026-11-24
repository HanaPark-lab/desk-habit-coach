"""공부 세션 API (API_SPECIFICATION.md). 모두 로그인 필요, 본인 것만."""
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from analyses.services import AnalysisError, drop_stream, predict_frame

from .models import BehaviorEvent, StudySession
from .serializers import BehaviorEventSerializer, StudySessionSerializer
from .services import event_service, time_engine

logger = logging.getLogger(__name__)
MAX_FRAME_BYTES = 2 * 1024 * 1024


def _valid_roi(roi):
    try:
        x1, y1, x2, y2 = (float(v) for v in roi)
    except (TypeError, ValueError):
        return False
    return 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1


class StudySessionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """POST 시작 · GET 목록/상세 · POST pause/resume/end/heartbeat · GET events."""

    serializer_class = StudySessionSerializer

    def get_queryset(self):
        return StudySession.objects.filter(user=self.request.user).prefetch_related("intervals")

    def _respond(self, fn, *args, ok_status=status.HTTP_200_OK):
        try:
            session = fn(*args)
        except time_engine.SessionError as e:
            return Response({"detail": e.message}, status=e.status)
        return Response(self.get_serializer(self.get_queryset().get(pk=session.pk)).data, status=ok_status)

    def create(self, request):
        mode = request.data.get("mode", StudySession.Mode.MANUAL)
        if mode not in StudySession.Mode.values:
            return Response({"detail": "mode는 MANUAL 또는 AI입니다."}, status=status.HTTP_400_BAD_REQUEST)
        return self._respond(time_engine.start, request.user, mode, ok_status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def mode(self, request, pk=None):
        """수동 ↔ AI 전환 (카메라 켜기/끄기). {"mode": "AI", "roi": [x1, y1, x2, y2], "phone_detection": false}
        roi·phone_detection은 선택."""
        mode, roi, phone = request.data.get("mode"), request.data.get("roi"), request.data.get("phone_detection")
        if mode not in StudySession.Mode.values:
            return Response({"detail": "mode는 MANUAL 또는 AI입니다."}, status=status.HTTP_400_BAD_REQUEST)
        if roi is not None and not _valid_roi(roi):
            return Response({"detail": "roi는 0~1 사이 [x1, y1, x2, y2] (x1<x2, y1<y2)입니다."}, status=status.HTTP_400_BAD_REQUEST)
        if phone is not None and not isinstance(phone, bool):
            return Response({"detail": "phone_detection은 true/false입니다."}, status=status.HTTP_400_BAD_REQUEST)
        session = self.get_object()
        if mode == StudySession.Mode.MANUAL:
            drop_stream(session.pk)
        return self._respond(time_engine.set_mode, session, mode, roi and [float(v) for v in roi], phone)

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        drop_stream(pk)  # 실시간 버퍼는 휴식 전후를 잇지 않음
        return self._respond(time_engine.pause, self.get_object())

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._respond(time_engine.resume, self.get_object())

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        drop_stream(pk)
        return self._respond(time_engine.end, self.get_object())

    @action(detail=True, methods=["post"])
    def heartbeat(self, request, pk=None):
        """공부 화면이 30초마다 보냄. 끊긴 시간은 UNKNOWN으로 정산된다."""
        return self._respond(time_engine.heartbeat, self.get_object())

    @action(detail=True, methods=["post"])
    def frames(self, request, pk=None):
        """AI 모드: 카메라 프레임(JPEG) 1장 + seq → FastAPI → 착석·부재 판단. 프레임은 저장하지 않는다.
        seq는 세션 안에서 증가해야 하며, 이미 반영한 번호 이하면 상태를 바꾸지 않는다 (ignored=true)."""
        session = self.get_object()
        frame = request.FILES.get("frame")
        if not frame or frame.size > MAX_FRAME_BYTES:
            return Response({"detail": "2MB 이하 JPEG 프레임을 보내 주세요."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            seq = int(request.data.get("seq", ""))
        except ValueError:
            return Response({"detail": "seq(프레임 번호)가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)
        if session.mode != StudySession.Mode.AI:
            return Response({"detail": "카메라(AI) 모드에서만 프레임을 반영합니다."}, status=status.HTTP_409_CONFLICT)
        if session.status == StudySession.Status.ENDED:
            return Response({"detail": "이미 종료된 세션입니다."}, status=status.HTTP_409_CONFLICT)
        if seq <= session.last_seq:  # 중복·역순: AI 서버 버퍼에도 넣지 않음
            return Response({**self.get_serializer(session).data, "ignored": True})
        try:
            # 휴식 중에는 버퍼에 쌓지 않음 (stream_key 없이 착석 판단만)
            key = str(session.pk) if session.status == StudySession.Status.ACTIVE else ""
            result = predict_frame(frame.read(), session.roi, key, seq, session.phone_detection)
            phone = max((p["confidence"] for p in result["phones"]), default=None)
            kind = time_engine.classify(result)
            session, alert, ignored = time_engine.observe(session, seq, kind, phone)
            candidates = result.get("action_candidates", [])
            decision = event_service.RealtimeDecision(None, "ignored_frame" if ignored else "no_window")
            if not ignored and candidates:
                decision = event_service.record_realtime_decision(
                    session, candidates, result.get("model_profile"), result.get("model_version", ""), timezone.now(),
                )
        except AnalysisError as e:
            return Response({"detail": e.message, "error_code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except time_engine.SessionError as e:
            return Response({"detail": e.message}, status=e.status)
        data = self.get_serializer(self.get_queryset().get(pk=session.pk)).data
        if settings.REALTIME_DEBUG:
            logger.info(
                "realtime model=%s seq=%s probabilities=%s prediction=%s thresholds=%s applied=%s score=%s "
                "valid_pose_frames=%s buffer_steps=%s buffer_status=%s observation=%s state=%s decision=%s recorded_label=%s",
                result.get("model_version"), seq, {c["label"]: c["probability"] for c in candidates},
                candidates[0]["label"] if candidates else None, settings.EVENT_THRESHOLDS, decision.threshold, decision.score,
                result.get("valid_pose_frames"), result.get("buffer_steps"), result.get("buffer_status"), kind,
                data["current_state"], decision.reason, decision.event.action_label if decision.event else None,
            )
        return Response({**data, "persons": result["persons"], "phones": result["phones"], "phone_alert": alert,
                         "observation": kind, "ignored": ignored,
                         "action_candidates": result.get("action_candidates", []), "buffer_steps": result.get("buffer_steps", 0),
                         "recorded_event": decision.event.event_type if decision.event else ""})

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        return Response(BehaviorEventSerializer(self.get_object().events.all(), many=True).data)


class BehaviorEventViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """GET 내 행동 기록 · PATCH {"is_valid": false} 로 오인식 정정 (집계에서 제외)."""

    serializer_class = BehaviorEventSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return BehaviorEvent.objects.filter(user=self.request.user)


@login_required
def session_page(request):
    """공부 세션 화면 (/study/): 타이머·시작/휴식/재개/종료·카메라 미리보기."""
    session = time_engine.open_session(request.user)
    start, end = time_engine.day_range(timezone.localdate())
    drinks = BehaviorEvent.objects.filter(user=request.user, is_valid=True, event_type=BehaviorEvent.EventType.DRINK,
                                          occurred_at__gte=start, occurred_at__lt=end).count()
    return render(request, "study/session.html", {"open_session_id": str(session.pk) if session else "", "drinks_today": drinks})
