import shutil
import tempfile
import time
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from study.models import BehaviorEvent
from study.services import time_engine

from . import camera_capture
from .habits import judge
from .models import AnalysisJob, PersonPrediction
from .services import AnalysisError
from .tasks import analyze_job

MEDIA = tempfile.mkdtemp()
THRESHOLDS = {"DRINK": 0.5, "MOVEMENT": 0.5}


def probs(drink=0.0, wave=0.0, walk=0.0, other=0.0):
    return {"drink_return": drink, "wave": wave, "walk_turn_walk": walk, "other": other}


def person(track_id, p, label=None):
    best = label or max(p, key=p.get)
    return {"track_id": track_id, "action_label": best, "confidence": p[best], "window_count": 3, "probabilities": p}


def tearDownModule():
    shutil.rmtree(MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=MEDIA, CAMERAS={"desk_cam_1": "http://camera.test/video"})
class AnalysisApiTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="unused-pass-1")
        self.bob = User.objects.create_user("bob", password="unused-pass-2")
        self.api = APIClient()
        self.api.force_authenticate(self.alice)
        patcher = mock.patch("analyses.views.analyze_job")  # 실제 Redis 대신 큐 등록만 확인
        self.queue = patcher.start()
        self.addCleanup(patcher.stop)

    def upload(self, name="clip.mp4", **extra):
        data = {"input_type": "UPLOAD", "video_file": SimpleUploadedFile(name, b"bytes"), **extra}
        with self.captureOnCommitCallbacks(execute=True):
            return self.api.post("/api/analyses/", data, format="multipart")

    def job_for(self, user, **fields):
        return AnalysisJob.objects.create(user=user, input_type="IPCAM", camera_key="desk_cam_1", **fields)

    def status(self, job):
        return self.api.get(f"/api/analyses/{job.pk}/status/").data

    def test_upload_creates_pending_job_and_queues_it(self):  # T05
        r = self.upload(title="오후 물")
        self.assertEqual((r.status_code, r.data["status"], r.data["session"]), (202, "PENDING", None))
        self.assertNotIn("video_file", r.data)
        self.queue.delay.assert_called_once_with(str(r.data["id"]))

    def test_upload_links_open_study_session(self):
        session = time_engine.start(self.alice)
        self.assertEqual(self.upload().data["session"], session.pk)

    def test_queue_down_marks_failure(self):
        self.queue.delay.side_effect = ConnectionError("redis down")
        job = AnalysisJob.objects.get(pk=self.upload().data["id"])  # 무한 PENDING이 아니어야 함
        self.assertEqual((job.status, job.error_code), ("FAILURE", "QUEUE_ERROR"))

    def test_txt_file_creates_failure_job_without_queue(self):  # T09
        r = self.upload("notes.txt")
        self.assertEqual((r.status_code, r.data["status"], r.data["error_code"]), (202, "FAILURE", "INVALID_FILE"))
        self.queue.delay.assert_not_called()

    def test_upload_without_file_rejected(self):
        self.assertEqual(self.api.post("/api/analyses/", {"input_type": "UPLOAD"}, format="multipart").status_code, 400)

    def test_ipcam_only_allowed_camera(self):
        ok = self.api.post("/api/analyses/", {"input_type": "IPCAM", "camera_key": "desk_cam_1"}, format="json")
        bad = self.api.post("/api/analyses/", {"input_type": "IPCAM", "camera_key": "http://evil.test"}, format="json")
        self.assertEqual((ok.status_code, bad.status_code), (202, 400))

    def test_anonymous_rejected(self):
        self.api.force_authenticate(None)
        self.assertEqual(self.api.get("/api/analyses/").status_code, 403)

    def test_other_users_job_is_invisible(self):  # T07
        job = self.job_for(self.bob)
        self.assertEqual(self.api.get("/api/analyses/").data["count"], 0)
        for method in ("get", "patch", "delete"):
            self.assertEqual(getattr(self.api, method)(f"/api/analyses/{job.pk}/").status_code, 404)
        self.assertEqual(self.api.get(f"/api/analyses/{job.pk}/status/").status_code, 404)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(f"/analyses/{job.pk}/").status_code, 404)
        self.assertTrue(AnalysisJob.objects.filter(pk=job.pk).exists())

    def test_patch_changes_only_title_and_memo(self):
        job = self.job_for(self.alice)
        r = self.api.patch(f"/api/analyses/{job.pk}/", {"title": "새 제목", "status": "SUCCESS"}, format="json")
        self.assertEqual(r.status_code, 200)
        job.refresh_from_db()
        self.assertEqual((job.title, job.status), ("새 제목", "PENDING"))

    def test_put_not_allowed(self):
        job = self.job_for(self.alice)
        self.assertEqual(self.api.put(f"/api/analyses/{job.pk}/", {}, format="json").status_code, 405)

    def test_record_and_delete_cascade(self):
        job = self.job_for(self.alice, status="SUCCESS")
        PersonPrediction.objects.create(job=job, track_id=1, action_label="drink_return", confidence=0.9, window_count=2,
                                        probabilities=probs(drink=0.9, wave=0.1))
        BehaviorEvent.objects.create(user=self.alice, job=job, action_label="drink_return", event_type="DRINK",
                                     confidence=0.9, dedup_key=f"job:{job.pk}")
        data = self.status(job)
        self.assertEqual((data["record"]["recorded"], data["record"]["event_type"]), (True, "DRINK"))
        self.assertEqual(data["predictions"][0]["event_type"], "DRINK")
        self.assertEqual(self.api.delete(f"/api/analyses/{job.pk}/").status_code, 204)
        self.assertFalse(PersonPrediction.objects.exists() or BehaviorEvent.objects.exists())

    def test_record_reasons(self):
        failed = self.job_for(self.alice, status="FAILURE", error_message="카메라 끊김")
        self.assertEqual(self.status(failed)["record"]["reason"], "카메라 끊김")
        nobody = self.job_for(self.alice, status="SUCCESS", error_message="영상에서 사람을 찾지 못했습니다.")
        self.assertEqual(self.status(nobody)["record"]["reason"], "영상에서 사람을 찾지 못했습니다.")
        other = self.job_for(self.alice, status="SUCCESS")
        PersonPrediction.objects.create(job=other, track_id=1, action_label="other", confidence=0.7, window_count=2,
                                        probabilities=probs(drink=0.3, other=0.7))
        data = self.status(other)
        self.assertIn("기타", data["record"]["reason"])
        self.assertEqual((data["predictions"][0]["event_type"], data["predictions"][0]["event_score"]), ("", 0.7))
        low = self.job_for(self.alice, status="SUCCESS")
        PersonPrediction.objects.create(job=low, track_id=1, action_label="drink_return", confidence=0.4, window_count=2,
                                        probabilities=probs(drink=0.4, wave=0.3, other=0.3))
        self.assertIn("판단 보류", self.status(low)["record"]["reason"])
        self.assertIsNone(self.status(self.job_for(self.alice))["record"])  # 진행 중

    def test_pages_render_without_camera_url(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get("/analyses/").status_code, 200)
        r = self.client.get("/analyses/new/")
        self.assertContains(r, 'id="page-config"')
        self.assertContains(r, "desk_cam_1")
        self.assertNotContains(r, "camera.test")  # 카메라 주소는 브라우저에 보내지 않음


class JudgeTests(SimpleTestCase):
    def test_drink_over_threshold(self):
        self.assertEqual(judge([person(1, probs(drink=0.8, wave=0.2))], THRESHOLDS), "DRINK")

    def test_movement_is_wave_plus_walk(self):
        self.assertEqual(judge([person(1, probs(drink=0.4, wave=0.3, walk=0.3))], THRESHOLDS), "MOVEMENT")

    def test_below_threshold_is_not_recorded(self):
        self.assertEqual(judge([person(1, probs(drink=0.45, wave=0.2, walk=0.1, other=0.25))], THRESHOLDS), "")

    def test_other_label_is_never_recorded(self):
        self.assertEqual(judge([person(1, probs(drink=0.5, other=0.5), label="other")], THRESHOLDS), "")

    def test_one_record_per_job_highest_person(self):
        people = [person(1, probs(drink=0.6, wave=0.4)), person(2, probs(drink=0.1, wave=0.9))]
        self.assertEqual(judge(people, THRESHOLDS), "MOVEMENT")

    def test_no_people(self):
        self.assertEqual(judge([], THRESHOLDS), "")


RESULT = {"model_version": "rf-test", "error_code": "", "message": "", "predictions": [person(1, probs(drink=0.8, wave=0.2))]}


@override_settings(MEDIA_ROOT=MEDIA, EVENT_THRESHOLDS=THRESHOLDS)
class AnalyzeTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tom", password="unused-pass-3")
        self.session = time_engine.start(self.user)
        self.job = AnalysisJob.objects.create(user=self.user, session=self.session, input_type="UPLOAD",
                                              video_file=SimpleUploadedFile("c.mp4", b"x"))

    def run_task(self):
        analyze_job.apply(args=[str(self.job.pk)])
        self.job.refresh_from_db()

    @mock.patch("analyses.tasks.predict_video", return_value=RESULT)
    def test_success_saves_predictions_and_event(self, _):
        self.run_task()
        self.assertEqual((self.job.status, self.job.model_version), ("SUCCESS", "rf-test"))
        self.assertEqual(self.job.predictions.count(), 1)
        event = BehaviorEvent.objects.get()
        self.assertEqual((event.event_type, event.job_id, event.session_id), ("DRINK", self.job.pk, self.session.pk))

    @mock.patch("analyses.tasks.predict_video", side_effect=AnalysisError("AI_UNAVAILABLE", "AI 분석 서버에 연결할 수 없습니다."))
    def test_ai_down_marks_failure(self, _):
        self.run_task()
        self.assertEqual((self.job.status, self.job.error_code), ("FAILURE", "AI_UNAVAILABLE"))
        self.assertFalse(BehaviorEvent.objects.exists())

    @mock.patch("analyses.tasks.predict_video", return_value={**RESULT, "predictions": [], "error_code": "NO_PERSON", "message": "영상에서 사람을 찾지 못했습니다."})
    def test_no_person_is_success_without_event(self, _):
        self.run_task()
        self.assertEqual((self.job.status, self.job.error_code), ("SUCCESS", "NO_PERSON"))
        self.assertFalse(BehaviorEvent.objects.exists())

    @mock.patch("analyses.tasks.predict_video", return_value=RESULT)
    def test_runs_only_once(self, predict):
        self.run_task()
        self.run_task()
        self.assertEqual((predict.call_count, self.job.predictions.count(), BehaviorEvent.objects.count()), (1, 1, 1))


class FakeCamera:
    """cv2.VideoCapture 대신: 약 100fps로 프레임을 주다가 frames개 후 끊김."""
    frames = 10_000

    def __init__(self, url, *args):
        self.url, self.left = url, self.frames

    def isOpened(self):
        return self.url != "bad"

    def read(self):
        time.sleep(0.01)
        if self.left <= 0:
            return False, None
        self.left -= 1
        return True, np.zeros((48, 64, 3), np.uint8)

    def release(self):
        pass


class CameraCaptureTests(SimpleTestCase):
    def test_capture_writes_exact_length(self):
        with tempfile.TemporaryDirectory() as d:  # 모듈 공용 MEDIA는 테스트 순서에 따라 먼저 지워질 수 있음
            out = Path(d) / "cam_ok.mp4"
            with mock.patch.object(camera_capture.cv2, "VideoCapture", FakeCamera):
                camera_capture.capture("ok", 1, out)
            self.assertEqual(int(cv2.VideoCapture(str(out)).get(cv2.CAP_PROP_FRAME_COUNT)), camera_capture.OUT_FPS)

    def test_unreachable_camera(self):
        with mock.patch.object(camera_capture.cv2, "VideoCapture", FakeCamera):
            with self.assertRaises(AnalysisError) as e:
                camera_capture.capture("bad", 1, Path(MEDIA) / "cam_bad.mp4")
        self.assertEqual(e.exception.code, "CAMERA_UNAVAILABLE")

    def test_stream_drop(self):
        class Dropping(FakeCamera):
            frames = 5
        with mock.patch.object(camera_capture.cv2, "VideoCapture", Dropping), \
                mock.patch.object(camera_capture, "STALL_SECONDS", 0.2):
            with self.assertRaises(AnalysisError) as e:
                camera_capture.capture("ok", 2, Path(MEDIA) / "cam_drop.mp4")
        self.assertEqual(e.exception.code, "CAMERA_LOST")


@override_settings(CAMERAS={"desk_cam_1": "http://camera.test/video"})
class CameraStreamTests(TestCase):
    """IP Webcam 실시간 미리보기: 허용된 카메라만 서버가 중계, 주소는 브라우저에 노출하지 않음."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("cam", password="unused-pass-9"))

    def fake_hub(self, *jpegs):
        hub = mock.Mock()
        hub.frames.return_value = iter(jpegs)
        return mock.patch("analyses.page_views.camera_hub.hub_for", return_value=hub)

    def test_relays_allowed_camera_as_mjpeg(self):
        with self.fake_hub(b"jpg1", b"jpg2") as hub_for:
            r = self.client.get("/analyses/cameras/desk_cam_1/stream/")
            body = b"".join(r.streaming_content)
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "multipart/x-mixed-replace; boundary=frame"))
        self.assertEqual(body.count(b"--frame"), 2)
        hub_for.assert_called_once_with("desk_cam_1", "http://camera.test/video")

    def test_access_rules(self):
        self.assertEqual(self.client.get("/analyses/cameras/http%3A%2F%2Fevil/stream/").status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get("/analyses/cameras/desk_cam_1/stream/").status_code, 403)
        self.assertEqual(self.client.get("/analyses/cameras/desk_cam_1/stream/?token=wrong").status_code, 403)
        from .page_views import relay_token
        with self.fake_hub(b"jpg"):  # Celery는 로그인 대신 토큰
            self.assertEqual(self.client.get(f"/analyses/cameras/desk_cam_1/stream/?token={relay_token('desk_cam_1')}").status_code, 200)

    def test_camera_down(self):
        with self.fake_hub():
            self.assertEqual(self.client.get("/analyses/cameras/desk_cam_1/stream/").status_code, 502)

    @mock.patch("analyses.camera_hub.requests.get")
    def test_hub_splits_mjpeg_into_jpegs(self, get):
        from .camera_hub import CameraHub
        jpg = b"\xff\xd8abc\xff\xd9"
        stream = get.return_value.__enter__.return_value
        stream.iter_content.return_value = iter([b"--b\r\n" + jpg[:3], jpg[3:] + b"\r\n"])
        self.assertEqual(list(CameraHub("http://camera.test/video").frames(timeout=1)), [jpg])
