"""공부 세션·행동 기록·대시보드 테스트 (TEST_CASES.md S01·S03·S04·S05·S07·S08·S10, T08)."""
from datetime import datetime, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from analyses.models import AnalysisJob, PersonPrediction
from analyses.services import AnalysisError

from .models import BehaviorEvent
from .services import event_service
from .services import time_engine as te

T0 = timezone.make_aware(datetime(2026, 11, 24, 10, 0))


def at(minutes):
    """시계를 T0 + minutes 분으로 고정."""
    return mock.patch("django.utils.timezone.now", return_value=T0 + timedelta(minutes=minutes))


def event(user, kind="DRINK", valid=True, key=None, **extra):
    return BehaviorEvent.objects.create(user=user, action_label="drink_return" if kind == "DRINK" else "wave",
                                        event_type=kind, confidence=0.8, is_valid=valid,
                                        dedup_key=key or f"test:{BehaviorEvent.objects.count()}", **extra)


class TimeEngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("una", password="unused-pass-1")

    def no_timeout(self):
        patcher = mock.patch.object(te, "HEARTBEAT_TIMEOUT", timedelta(hours=10))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_start_pause_resume_end_totals(self):  # S01·S07
        self.no_timeout()
        with at(0):
            s = te.start(self.user)
        with at(50):
            te.pause(s)
        with at(60):
            te.resume(s)
        with at(90):
            s = te.end(s)
        totals = te.seconds_by_state(s.intervals.all())
        self.assertEqual((totals["STUDY"], totals["BREAK"], totals["UNKNOWN"]), (80 * 60, 10 * 60, 0))
        self.assertEqual(sum(totals.values()), 90 * 60)  # 구간 합계 = 세션 전체 (겹침 없음)

    def test_only_one_open_session(self):  # S08
        te.start(self.user)
        with self.assertRaises(te.SessionError):
            te.start(self.user)

    def test_invalid_transitions(self):
        s = te.start(self.user)
        with self.assertRaises(te.SessionError):
            te.resume(s)
        te.end(s)
        with self.assertRaises(te.SessionError):
            te.pause(s)

    def test_lost_heartbeat_counts_as_unknown(self):  # S04
        with at(0):
            s = te.start(self.user)
        with at(1):
            te.heartbeat(s)
        with at(20):  # 19분 동안 신호 없음 → 공부가 아니라 확인 불가
            te.pause(s)
        with at(30):
            s = te.end(s)
        totals = te.seconds_by_state(s.intervals.all())
        self.assertEqual((totals["STUDY"], totals["UNKNOWN"], totals["BREAK"]), (60, 19 * 60, 10 * 60))

    def test_heartbeat_after_gap_resumes_study(self):
        with at(0):
            s = te.start(self.user)
        with at(10):
            te.heartbeat(s)
        with at(11):  # 다시 연결된 뒤 1분 공부 (90초 안이라 정상)
            s = te.end(s)
        totals = te.seconds_by_state(s.intervals.all())
        self.assertEqual((totals["STUDY"], totals["UNKNOWN"]), (60, 10 * 60))

    def test_day_split_at_midnight(self):
        self.no_timeout()
        night = timezone.make_aware(datetime(2026, 11, 24, 23, 30))
        with mock.patch("django.utils.timezone.now", return_value=night):
            s = te.start(self.user)
        with mock.patch("django.utils.timezone.now", return_value=night + timedelta(hours=1)):
            te.end(s)
        self.assertEqual(te.day_seconds(self.user, night.date())["STUDY"], 1800)
        self.assertEqual(te.day_seconds(self.user, (night + timedelta(hours=1)).date())["STUDY"], 1800)


class FocusModeTests(TestCase):  # S02: 자리 비움·복귀 자동 전환, 휴대폰 지속 감지
    def setUp(self):
        self.user = User.objects.create_user("fox", password="unused-pass-7")
        with at(0):
            self.s = te.start(self.user)

    def see(self, minutes, present=True, phone=None):
        with at(minutes):
            return te.observe(self.s, present, phone)

    def states(self):
        return [(i.state, i.source) for i in self.s.intervals.all()]

    def test_away_after_5s_then_back(self):
        self.see(0.5)                      # 30초에 보임
        self.see(0.55, present=False)      # 3초 뒤 안 보임 → 아직 공부
        self.assertEqual(self.states(), [("STUDY", "MANUAL")])
        self.see(0.7, present=False)       # 12초째 안 보임 → 30초 시점부터 자리 비움
        self.see(1.0)                      # 다시 보임 → 공부
        self.assertEqual(self.states(), [("STUDY", "MANUAL"), ("AWAY", "AUTO"), ("STUDY", "AUTO")])
        with at(1.0):
            totals = te.seconds_by_state(self.s.intervals.all())
        self.assertEqual((totals["STUDY"], totals["AWAY"]), (30, 30))

    def test_phone_for_10s_records_one_distraction(self):
        _, a1 = self.see(0.5, phone=0.8)
        _, a2 = self.see(0.6, phone=0.8)   # 6초
        _, a3 = self.see(0.7, phone=0.9)   # 12초 → 1건 + 알림
        _, a4 = self.see(0.8, phone=0.9)   # 같은 연속 구간 → 추가 기록 없음
        self.assertEqual((a1, a2, a3, a4), (False, False, True, False))
        self.see(0.85)                     # 휴대폰 사라짐 → 연속 구간 리셋
        self.assertEqual(BehaviorEvent.objects.filter(event_type="PHONE").count(), 1)

    def test_paused_session_not_changed_by_camera(self):
        with at(1):
            te.pause(self.s)
        self.see(2, present=False)
        self.assertEqual(self.states()[-1], ("BREAK", "MANUAL"))

    @mock.patch("study.views.predict_frame", return_value={"persons": [{"track_id": 1, "box": [0, 0, 1, 1], "keypoints": []}], "phones": []})
    def test_frames_api(self, predict):
        api = APIClient()
        api.force_authenticate(self.user)
        r = api.post(f"/api/study/sessions/{self.s.pk}/frames/", {"frame": SimpleUploadedFile("f.jpg", b"jpg", "image/jpeg")}, format="multipart")
        self.assertEqual((r.status_code, r.data["current_state"], len(r.data["persons"]), r.data["phone_alert"]), (200, "STUDY", 1, False))
        self.assertEqual(api.post(f"/api/study/sessions/{self.s.pk}/frames/", {}, format="multipart").status_code, 400)
        predict.side_effect = AnalysisError("AI_UNAVAILABLE", "AI 분석 서버에 연결할 수 없습니다.")
        r = api.post(f"/api/study/sessions/{self.s.pk}/frames/", {"frame": SimpleUploadedFile("f.jpg", b"jpg", "image/jpeg")}, format="multipart")
        self.assertEqual(r.status_code, 503)


@override_settings(EVENT_THRESHOLDS={"DRINK": 0.5, "MOVEMENT": 0.5})
class EventServiceTests(TestCase):  # S05
    def setUp(self):
        self.user = User.objects.create_user("vic", password="unused-pass-2")
        self.session = te.start(self.user)
        self.job = AnalysisJob.objects.create(user=self.user, session=self.session, input_type="UPLOAD", status="SUCCESS")

    def preds(self, label, p):
        return [{"track_id": 1, "action_label": label, "confidence": max(p.values()), "window_count": 2, "probabilities": p}]

    def test_records_once_per_job(self):
        p = self.preds("drink_return", {"drink_return": 0.8, "wave": 0.2})
        e1 = event_service.record_from_job(self.job, p)
        e2 = event_service.record_from_job(self.job, p)
        self.assertEqual((e1.pk, e1.event_type, e1.session_id, BehaviorEvent.objects.count()), (e2.pk, "DRINK", self.session.pk, 1))

    def test_other_or_low_score_not_recorded(self):
        self.assertIsNone(event_service.record_from_job(self.job, self.preds("other", {"other": 0.6, "drink_return": 0.4})))
        self.assertIsNone(event_service.record_from_job(self.job, self.preds("drink_return", {"drink_return": 0.4, "other": 0.35, "wave": 0.25})))


class StudyApiTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="unused-pass-3")
        self.bob = User.objects.create_user("bob", password="unused-pass-4")
        self.api = APIClient()
        self.api.force_authenticate(self.alice)

    def test_session_flow(self):  # S01·S03
        r = self.api.post("/api/study/sessions/")
        self.assertEqual((r.status_code, r.data["status"], r.data["current_state"]), (201, "ACTIVE", "STUDY"))
        self.assertEqual(self.api.post("/api/study/sessions/").status_code, 409)  # 동시 활성 세션 방지
        base = f"/api/study/sessions/{r.data['id']}"
        self.assertEqual(self.api.post(f"{base}/pause/").data["current_state"], "BREAK")
        self.assertEqual(self.api.post(f"{base}/resume/").data["current_state"], "STUDY")
        self.assertEqual(self.api.post(f"{base}/end/").data["status"], "ENDED")
        self.assertEqual(self.api.post(f"{base}/pause/").status_code, 409)

    def test_other_users_session_is_invisible(self):  # S08
        s = te.start(self.bob)
        self.assertEqual(self.api.get(f"/api/study/sessions/{s.pk}/").status_code, 404)
        self.assertEqual(self.api.post(f"/api/study/sessions/{s.pk}/end/").status_code, 404)
        self.api.force_authenticate(None)
        self.assertEqual(self.api.post("/api/study/sessions/").status_code, 403)

    def test_event_correction(self):  # S10
        mine, theirs = event(self.alice), event(self.bob)
        r = self.api.patch(f"/api/study/events/{mine.pk}/", {"is_valid": False, "event_type": "MOVEMENT"}, format="json")
        mine.refresh_from_db()
        self.assertEqual((r.status_code, mine.is_valid, mine.event_type), (200, False, "DRINK"))  # 정정만 가능
        self.assertEqual(self.api.patch(f"/api/study/events/{theirs.pk}/", {"is_valid": False}, format="json").status_code, 404)

    def test_today_counts_only_valid_own_events(self):
        event(self.alice), event(self.alice), event(self.alice, valid=False), event(self.alice, "MOVEMENT"), event(self.bob)
        data = self.api.get("/api/dashboard/today/").data
        self.assertEqual(data["events"], {"DRINK": 2, "MOVEMENT": 1, "PHONE": 0})
        self.assertEqual(set(data["seconds"]), {"STUDY", "BREAK", "AWAY", "UNKNOWN"})
        self.assertEqual(len(self.api.get("/api/dashboard/weekly/").data["days"]), 7)


class PageTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("boss", password="unused-pass-5", is_staff=True)
        self.member = User.objects.create_user("mia", password="unused-pass-6")

    def test_member_pages(self):
        self.client.force_login(self.member)
        te.start(self.member)
        for url in ("/dashboard/", "/study/", "/reports/", "/analyses/", "/analyses/new/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertNotContains(self.client.get("/dashboard/"), 'href="/staff/dashboard/"')

    def test_anonymous_redirected_to_login(self):
        for url in ("/dashboard/", "/study/", "/reports/", "/staff/dashboard/"):
            self.assertRedirects(self.client.get(url), f"/accounts/login/?next={url}")

    def test_staff_dashboard_uses_real_db_counts(self):  # T08
        ok = AnalysisJob.objects.create(user=self.member, input_type="UPLOAD", status="SUCCESS", processing_ms=2000)
        PersonPrediction.objects.create(job=ok, track_id=1, action_label="drink_return", confidence=0.8, window_count=2, probabilities={})
        PersonPrediction.objects.create(job=ok, track_id=2, action_label="wave", confidence=0.7, window_count=2, probabilities={})
        event(self.member, job=ok)
        ng = AnalysisJob.objects.create(user=self.member, input_type="UPLOAD", status="SUCCESS", processing_ms=4000)
        PersonPrediction.objects.create(job=ng, track_id=1, action_label="other", confidence=0.6, window_count=1, probabilities={})
        AnalysisJob.objects.create(user=self.member, input_type="UPLOAD", status="FAILURE")
        AnalysisJob.objects.create(user=self.staff, input_type="IPCAM", camera_key="desk_cam_1")

        self.client.force_login(self.member)
        self.assertEqual(self.client.get("/staff/dashboard/").status_code, 403)
        self.client.force_login(self.staff)
        r = self.client.get("/staff/dashboard/")
        self.assertEqual({a["label"]: a["count"] for a in r.context["actions"]},
                         {"drink_return": 1, "wave": 1, "walk_turn_walk": 0, "other": 1})
        self.assertEqual({s["status"]: s["count"] for s in r.context["statuses"]},
                         {"SUCCESS": 2, "FAILURE": 1, "STARTED": 0, "PENDING": 1})
        s = r.context["stats"]
        self.assertEqual((s["users"], s["total"], s["success_rate"], s["record_rate"], s["recorded"], s["avg_seconds"]),
                         (2, 4, 66.7, 50.0, 1, 3.0))
        self.assertEqual({x["label"]: x["count"] for x in r.context["segments"]},
                         {"기록됨": 1, "기록 안 함": 1, "실패": 1, "대기·분석 중": 1})
        self.assertContains(r, 'class="barlist"')
        self.assertContains(r, 'id="status-chart"')
        self.assertContains(self.client.get("/dashboard/"), 'href="/staff/dashboard/"')
