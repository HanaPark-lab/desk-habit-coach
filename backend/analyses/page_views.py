"""분석 화면 (UI_UX.md): 분석 화면(요청·결과) · 작업 상세 · 카메라 중계."""
import time

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.crypto import constant_time_compare, salted_hmac

from . import camera_hub

from .models import AnalysisJob


def _page_config():
    return {
        "cameras": sorted(settings.CAMERAS),  # 별칭만. 카메라 주소는 브라우저에 보내지 않음
        "default_seconds": settings.DEFAULT_CAPTURE_SECONDS,
    }


@login_required
def job_list(request):
    """교과 '사용자 분석 화면': 입력 선택·분석 시작·상태·사람별 결과을 한 화면에."""
    return render(request, "analyses/list.html", {"page_config": _page_config()})


STREAM_MAX_SECONDS = 600  # 미리보기 1회 최대 10분 (서버 스레드를 오래 붙잡지 않게)


def relay_token(key):
    """Celery가 로그인 없이 중계 영상을 받을 때 쓰는 비밀 토큰 (SECRET_KEY 기반, 카메라별)."""
    return salted_hmac("camera-relay", key).hexdigest()


def camera_stream(request, key):
    """허용된 카메라 영상(MJPEG) 중계. 카메라 연결은 허브 1개를 미리보기·Celery 수집이 함께 쓴다.
    로그인 사용자 또는 Celery(토큰)만 접근. 카메라 주소는 브라우저에 노출하지 않는다."""
    url = settings.CAMERAS.get(key)
    if not url:
        raise Http404("허용되지 않은 카메라입니다.")
    if not (request.user.is_authenticated or constant_time_compare(request.GET.get("token", ""), relay_token(key))):
        return HttpResponse(status=403)
    frames = camera_hub.hub_for(key, url).frames()
    first = next(frames, None)
    if first is None:
        return HttpResponse("카메라에 연결할 수 없습니다.", status=502)

    def limited():
        deadline = time.monotonic() + STREAM_MAX_SECONDS
        yield first
        for jpg in frames:
            yield jpg
            if time.monotonic() > deadline:
                break

    response = StreamingHttpResponse(camera_hub.mjpeg(limited()), content_type="multipart/x-mixed-replace; boundary=frame")
    response["Cache-Control"] = "no-store"
    return response


@login_required
def job_detail(request, pk):
    job = get_object_or_404(AnalysisJob, pk=pk, user=request.user)  # 다른 사람 작업은 404
    return render(request, "analyses/detail.html", {"job": job})
