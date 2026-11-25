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


def sec(seconds):
    return mock.patch("django.utils.timezone.now", return_value=T0 + timedelta(seconds=seconds))


PRESENT_FRAME = {"persons": [{"track_id": 1, "box": [0.3, 0.2, 0.7, 0.9], "keypoints": []}], "phones": [],
                 "presence_candidate": True, "quality_passed": True, "track_count": 1}


class AiBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("fox", password="unused-pass-7")
        with sec(0):
            self.s = te.start(self.user, te.Mode.AI)
        self.seq = 0

    def see(self, seconds, kind=te.PRESENT, phone=None, seq=None):
        self.seq += 1
        with sec(seconds):
            return te.observe(self.s, seq or self.seq, kind, phone)

    def see_each(self, a, b, kind=te.PRESENT):
        for t in range(a, b + 1):
            self.see(t, kind)

    def states(self):
        return [(i.state, i.source) for i in self.s.intervals.all()]

    def totals(self, seconds):
        self.s.refresh_from_db()
        with sec(seconds):
            return te.seconds_by_state(self.s.intervals.all())


class AiModeTests(AiBase):  # S01~S04: AI 착석 추정 상태 전환
    def test_starts_unknown_and_needs_3s_stable_presence(self):
        self.assertEqual(self.states(), [("UNKNOWN", "AUTO")])
        self.see_each(1, 3)
        self.assertEqual(self.states()[-1][0], "UNKNOWN")   # 2초 → 아직
        self.see(4)                                        # 3초 안정 → 1초 시점부터 STUDY
        self.assertEqual(self.states(), [("UNKNOWN", "AUTO"), ("STUDY", "AUTO")])
        self.assertEqual(self.s.intervals.last().started_at, T0 + timedelta(seconds=1))

    def test_away_after_5s_absence_then_back(self):
        self.see_each(1, 9)
        self.see_each(10, 14, te.ABSENT)
        self.assertEqual(self.states()[-1][0], "STUDY")    # 부재 4초 → 아직 공부
        self.see(15, te.ABSENT)                            # 5초 → 10초 시점부터 복귀 확인 중
        self.see_each(16, 18)
        self.assertEqual(self.states()[-1][0], "AWAY_PENDING")  # 복귀 2초 → 아직
        self.see(19)                                       # 3초 → 16초 시점부터 STUDY, 이탈 6초는 휴식
        self.assertEqual([s for s, _ in self.states()], ["UNKNOWN", "STUDY", "BREAK", "STUDY"])
        t = self.totals(19)
        self.assertEqual((t["UNKNOWN"], t["STUDY"], t["BREAK"]), (1, 12, 6))
        self.assertEqual(sum(t.values()), 19)  # 겹침 없음, 합계 = 경과 시간

    def test_unclear_frames_and_disconnect_become_unknown(self):
        self.see_each(1, 4)                     # STUDY (1초~)
        self.see_each(5, 12, te.UNCLEAR)        # 가림·다중 인물: 유효 관측 아님 → 4초 + 5초 지나면 UNKNOWN
        self.assertEqual([s for s, _ in self.states()], ["UNKNOWN", "STUDY", "UNKNOWN"])
        self.see_each(13, 16)                   # 다시 STUDY (13초~)
        self.s.refresh_from_db()
        with sec(30):                           # 프레임이 끊김 → 상태 API·집계 모두 16초부터 UNKNOWN
            self.assertEqual(te.current_state(self.s), ("UNKNOWN", T0 + timedelta(seconds=16)))
        t = self.totals(30)
        self.assertEqual((t["STUDY"], t["UNKNOWN"], sum(t.values())), (6, 24, 30))

    def test_heartbeat_does_not_restore_study(self):
        self.see_each(1, 4)
        with sec(20):
            te.heartbeat(self.s)
        self.assertEqual([s for s, _ in self.states()], ["UNKNOWN", "STUDY", "UNKNOWN"])

    def test_duplicate_and_old_frames_ignored(self):
        self.assertFalse(self.see(1, seq=5)[2])
        self.assertTrue(self.see(2, te.ABSENT, seq=5)[2])  # 같은 번호
        self.assertTrue(self.see(3, te.ABSENT, seq=4)[2])  # 역순
        self.s.refresh_from_db()
        self.assertEqual((self.s.last_seq, self.s.absent_since), (5, None))

    def test_break_is_manual_and_resume_enters_unknown(self):
        self.see_each(1, 4)
        with sec(5):
            te.pause(self.s)
        self.see_each(6, 20, te.ABSENT)
        self.assertEqual(self.states()[-1], ("BREAK", "MANUAL"))
        with sec(21):
            te.resume(self.s)
        self.assertEqual(self.states()[-1], ("UNKNOWN", "AUTO"))

    def test_ended_session_rejects_frames(self):
        with sec(5):
            te.end(self.s)
        with self.assertRaises(te.SessionError):
            self.see(6)

    def test_phone_for_10s_records_one_distraction(self):
        alerts = [self.see(t, phone=0.8)[1] for t in (30, 36, 42, 48)]
        self.assertEqual(alerts, [False, False, True, False])  # 12초째 1건, 같은 연속 구간은 추가 없음
        self.see(51)
        self.assertEqual(BehaviorEvent.objects.filter(event_type="PHONE").count(), 1)


class BreakRuleTests(AiBase):  # STUDY_BREAK_IMPLEMENTATION.md B01~B12 (B10 중복·역순, B11 시작/재개, B12 수동은 위 테스트)
    def see_range(self, a, b, kind=te.PRESENT, step=2):
        for t in range(a, b + 1, step):
            self.see(t, kind)

    def leave_and_return(self, back_at):
        """1~9초 공부 → 10초부터 이탈 → back_at초부터 3초간 복귀."""
        self.see_range(1, 9, step=1)
        self.see_range(10, back_at - 2, te.ABSENT)
        self.see_range(back_at, back_at + 3, step=1)
        return self.totals(back_at + 3)

    def test_b01_short_absence_creates_nothing(self):
        self.see_range(1, 4, step=1)
        self.see_range(5, 6, te.ABSENT, step=1)  # 2초만 미감지
        self.see_range(7, 10, step=1)
        self.assertEqual([s for s, _ in self.states()], ["UNKNOWN", "STUDY"])

    def test_b02_return_after_10min_is_all_break(self):
        t = self.leave_and_return(610)
        self.assertEqual([s for s, _ in self.states()], ["UNKNOWN", "STUDY", "BREAK", "STUDY"])
        self.assertEqual((t["BREAK"], t["AWAY"], t["AWAY_PENDING"]), (600, 0, 0))

    def test_b03_return_exactly_15min_is_break(self):
        t = self.leave_and_return(910)  # 첫 복귀 관측이 이탈 900초 뒤
        self.assertEqual((t["BREAK"], t["AWAY"]), (900, 0))

    def test_return_one_second_over_15min_is_away(self):
        t = self.leave_and_return(911)
        self.assertEqual((t["BREAK"], t["AWAY"]), (0, 901))

    def test_b04_return_after_25min_is_all_away(self):
        self.see_range(1, 9, step=1)
        self.see_range(10, 1000, te.ABSENT)
        self.assertEqual(self.states()[-1][0], "AWAY")     # 15분 넘게 미복귀 → 같은 구간을 AWAY로 확정
        self.see_range(1002, 1508, te.ABSENT)
        self.see_range(1510, 1513, step=1)
        t = self.totals(1513)
        self.assertEqual([s for s, _ in self.states()], ["UNKNOWN", "STUDY", "AWAY", "STUDY"])
        self.assertEqual((t["AWAY"], t["BREAK"]), (1500, 0))

    @override_settings(EVENT_THRESHOLDS={"DRINK": 0.5, "MOVEMENT": 0.5})
    def test_b05_b06_actions_do_not_change_time_state(self):
        self.see_range(1, 9, step=1)
        before = self.states()
        walk = event_service.record_realtime_decision(self.s, cands(walk=0.8, other=0.2), "service", "rf", T0 + timedelta(seconds=9)).event
        drink = event_service.record_realtime_decision(self.s, cands(drink=0.8, other=0.2), "service", "rf", T0 + timedelta(seconds=9)).event
        self.assertEqual((walk.event_type, walk.action_label, drink.event_type), ("MOVEMENT", "walk_turn_walk", "DRINK"))
        self.assertEqual(self.states(), before)

    def test_b07_disconnect_during_pending_is_away_then_unknown(self):
        self.see_range(1, 9, step=1)
        self.see_range(10, 20, te.ABSENT, step=1)           # 15초부터 복귀 확인 중(10초~)
        with sec(60):
            te.heartbeat(self.s)                            # 20초 이후 관측 없음
        self.assertEqual([s for s, _ in self.states()], ["UNKNOWN", "STUDY", "AWAY", "UNKNOWN"])
        t = self.totals(60)
        self.assertEqual((t["STUDY"], t["AWAY"], t["UNKNOWN"], sum(t.values())), (9, 10, 41, 60))

    def test_b08_manual_break_not_overwritten(self):
        self.see_range(1, 9, step=1)
        with sec(10):
            te.pause(self.s)
        self.see_range(11, 1210, te.ABSENT, step=10)
        with sec(1210):
            te.resume(self.s)
        t = self.totals(1210)
        self.assertEqual((t["BREAK"], t["AWAY"]), (1200, 0))

    def test_b09_end_while_pending_is_away(self):
        self.see_range(1, 9, step=1)
        self.see_range(10, 20, te.ABSENT, step=1)
        with sec(22):
            s = te.end(self.s)
        self.assertEqual([i.state for i in s.intervals.all()], ["UNKNOWN", "STUDY", "AWAY"])
        self.assertFalse(s.intervals.filter(ended_at__isnull=True).exists())

    def test_pending_shown_in_api_fields(self):
        self.see_range(1, 9, step=1)
        self.see_range(10, 20, te.ABSENT, step=1)
        from .serializers import StudySessionSerializer
        self.s.refresh_from_db()
        with sec(20):
            data = StudySessionSerializer(self.s).data
        self.assertEqual((data["state"], data["pending_seconds"], data["study_seconds"]), ("AWAY_PENDING", 10, 9))


class ModeSwitchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("max", password="unused-pass-8")

    def test_manual_and_ai_time_are_separate(self):
        with sec(0):
            s = te.start(self.user)
        with sec(60):
            te.set_mode(s, te.Mode.AI)                   # 카메라 켬 → 확인 중부터
        with sec(120):
            s = te.set_mode(s, te.Mode.MANUAL)
        self.assertEqual([(i.state, i.source) for i in s.intervals.all()],
                         [("STUDY", "MANUAL"), ("UNKNOWN", "AUTO"), ("STUDY", "MANUAL")])
        with sec(180):
            self.assertEqual(te.study_seconds_by_source(s.intervals.all()), {"MANUAL": 120, "AUTO": 0})
        with self.assertRaises(te.SessionError):
            with sec(181):
                te.observe(s, 1, te.PRESENT)             # 수동 모드는 프레임 반영 안 함

    def test_classify(self):
        self.assertEqual(te.classify(PRESENT_FRAME), te.PRESENT)
        self.assertEqual(te.classify({"presence_candidate": False, "quality_passed": True, "track_count": 0}), te.ABSENT)
        self.assertEqual(te.classify({"presence_candidate": False, "quality_passed": True, "track_count": 2}), te.UNCLEAR)
        self.assertEqual(te.classify({"presence_candidate": False, "quality_passed": False, "track_count": 1}), te.UNCLEAR)


class FramesApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ray", password="unused-pass-9")
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.base = f"/api/study/sessions/{self.api.post('/api/study/sessions/', {'mode': 'AI'}, format='json').data['id']}"

    def frame(self, seq=None):
        data = {"frame": SimpleUploadedFile("f.jpg", b"jpg", "image/jpeg")}
        if seq is not None:
            data["seq"] = seq
        return self.api.post(f"{self.base}/frames/", data, format="multipart")

    @mock.patch("study.views.predict_frame", return_value=PRESENT_FRAME)
    def test_frames_api(self, predict):
        r = self.frame(1)
        self.assertEqual((r.status_code, r.data["mode"], r.data["current_state"], r.data["observation"], r.data["ignored"]),
                         (200, "AI", "UNKNOWN", "present", False))
        self.assertTrue(self.frame(1).data["ignored"])
        self.assertEqual(self.frame().status_code, 400)                      # seq 없음
        self.assertEqual(self.api.post(f"{self.base}/frames/", {"seq": 2}, format="multipart").status_code, 400)
        predict.side_effect = AnalysisError("AI_UNAVAILABLE", "AI 분석 서버에 연결할 수 없습니다.")
        self.assertEqual(self.frame(3).status_code, 503)
        predict.side_effect = None
        r = self.api.post(f"{self.base}/mode/", {"mode": "MANUAL"}, format="json")
        self.assertEqual((r.data["mode"], r.data["current_state"]), ("MANUAL", "STUDY"))
        self.assertEqual(self.frame(4).status_code, 409)                     # 수동 모드
        self.assertEqual(self.api.post(f"{self.base}/mode/", {"mode": "AI", "roi": [0.5, 0, 0.2, 1]}, format="json").status_code, 400)
        r = self.api.post(f"{self.base}/mode/", {"mode": "AI", "roi": [0.1, 0, 0.9, 1]}, format="json")
        self.assertEqual((r.data["mode"], r.data["roi"]), ("AI", [0.1, 0.0, 0.9, 1.0]))
        self.frame(5)
        self.assertEqual(predict.call_args.args[1], [0.1, 0.0, 0.9, 1.0])  # ROI를 FastAPI로 전달


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


def cands(drink=0.0, wave=0.0, walk=0.0, other=0.0):
    p = {"drink_return": drink, "wave": wave, "walk_turn_walk": walk, "other": other}
    return sorted(({"label": k, "probability": v} for k, v in p.items()), key=lambda c: -c["probability"])


@override_settings(EVENT_THRESHOLDS={"DRINK": 0.5, "MOVEMENT": 0.5})
class RealtimeEventTests(TestCase):  # S05·S06: episode당 1건, 중복·NG 보류
    def setUp(self):
        self.user = User.objects.create_user("rio", password="unused-pass-10")
        with sec(0):
            self.s = te.start(self.user, te.Mode.AI)

    def window(self, seconds, c, profile="service"):
        return event_service.record_realtime_decision(self.s, c, profile, "rf-test", T0 + timedelta(seconds=seconds)).event

    def test_one_event_per_episode_and_cooldown(self):
        e1 = self.window(10, cands(drink=0.8, other=0.2))
        self.assertIsNone(self.window(11, cands(drink=0.9, other=0.1)))   # 같은 episode (연속 window)
        self.assertIsNone(self.window(12, cands(other=0.7, drink=0.3)))   # episode 끝
        self.assertIsNone(self.window(30, cands(drink=0.8, other=0.2)))   # 재진입했지만 60초 cooldown 안
        self.assertIsNone(self.window(31, cands(other=0.9)))
        e2 = self.window(80, cands(drink=0.7, other=0.3))                # cooldown 지남 → 새 기록
        self.assertEqual((e1.event_type, e1.source, e1.model_version, e1.action_label), ("DRINK", "REALTIME", "rf-test", "drink_return"))
        self.assertIsNotNone(e2)
        self.assertEqual(BehaviorEvent.objects.count(), 2)

    def test_wave_and_walk_are_distinct_episodes(self):
        wave = self.window(10, cands(wave=0.9))
        walk = self.window(11, cands(walk=0.9))
        self.assertIsNotNone(wave)
        self.assertIsNotNone(walk)
        self.assertEqual((wave.action_label, walk.action_label), ("wave", "walk_turn_walk"))
        self.assertIsNone(self.window(12, cands(walk=0.9)))
        self.assertIsNone(self.window(13, cands(wave=0.9)))
        self.assertEqual(BehaviorEvent.objects.count(), 2)

    def test_ng_low_score_and_course_not_recorded(self):
        self.assertIsNone(self.window(10, cands(other=0.6, drink=0.4)))  # 기타(타이핑 등) → 보류
        self.assertIsNone(self.window(11, cands(drink=0.45, other=0.3, wave=0.25)))
        self.assertIsNone(self.window(12, [{"label": "A001_x", "probability": 0.9}], profile="course"))
        movement = self.window(13, cands(wave=0.35, walk=0.3, drink=0.2, other=0.15))
        self.assertEqual((movement.event_type, movement.action_label), ("MOVEMENT", "wave"))

    def test_clip_and_realtime_not_double_counted(self):
        self.window(10, cands(drink=0.8))
        job = AnalysisJob.objects.create(user=self.user, input_type="UPLOAD", status="SUCCESS")
        AnalysisJob.objects.filter(pk=job.pk).update(created_at=T0 + timedelta(seconds=40))
        job.refresh_from_db()
        p = [{"track_id": 1, "action_label": "drink_return", "confidence": 0.8, "window_count": 2, "probabilities": {"drink_return": 0.8}}]
        with override_settings(EVENT_THRESHOLDS={"DRINK": 0.5, "MOVEMENT": 0.5}):
            self.assertIsNone(event_service.record_from_job(job, p))
        self.assertEqual(BehaviorEvent.objects.count(), 1)

    def test_paused_session_not_recorded(self):
        with sec(5):
            te.pause(self.s)
        self.assertIsNone(self.window(10, cands(drink=0.9)))

    def test_realtime_decision_explains_policy_without_changing_thresholds(self):
        def decision(seconds, candidates):
            return event_service.record_realtime_decision(
                self.s, candidates, "service", "rf-test", T0 + timedelta(seconds=seconds),
            )

        first = decision(10, cands(drink=0.9, other=0.1))
        self.assertEqual((first.reason, first.score, first.threshold), ("recorded", 0.9, 0.5))
        self.assertEqual(decision(11, cands(drink=0.8)).reason, "same_episode")
        self.assertEqual(decision(12, cands(other=0.7, drink=0.3)).reason, "other")
        self.assertEqual(decision(13, cands(drink=0.8)).reason, "cooldown")
        self.assertEqual(decision(14, cands(wave=0.4, drink=0.35, other=0.25)).reason, "below_threshold")
        self.assertEqual(BehaviorEvent.objects.count(), 1)

    @override_settings(REALTIME_DEBUG=True)
    @mock.patch("study.views.drop_stream")
    @mock.patch("study.views.predict_frame", return_value={**PRESENT_FRAME, "action_candidates": cands(drink=0.9), "buffer_steps": 30,
                                                          "model_profile": "service", "model_version": "rf-test",
                                                          "valid_pose_frames": 26, "buffer_status": "window"})
    def test_frames_api_records_realtime_event(self, predict, drop):
        api = APIClient()
        api.force_authenticate(self.user)
        base = f"/api/study/sessions/{self.s.pk}"
        with self.assertLogs("study.views", level="INFO") as logs:
            r = api.post(f"{base}/frames/", {"frame": SimpleUploadedFile("f.jpg", b"jpg", "image/jpeg"), "seq": 7}, format="multipart")
        for field in ("model=rf-test", "'wave': 0.0", "prediction=drink_return", "applied=0.5",
                      "valid_pose_frames=26", "state=UNKNOWN", "decision=recorded"):
            self.assertIn(field, logs.output[0])
        self.assertEqual((r.status_code, r.data["recorded_event"], r.data["buffer_steps"]), (200, "DRINK", 30))
        self.assertEqual(predict.call_args.args[2:], (str(self.s.pk), 7, False))   # stream_key·seq·휴대폰 감지 OFF
        r = api.post(f"{base}/frames/", {"frame": SimpleUploadedFile("f.jpg", b"jpg", "image/jpeg"), "seq": 6}, format="multipart")
        self.assertTrue(r.data["ignored"])
        self.assertEqual(predict.call_count, 1)                                   # 역순 프레임은 AI 서버로 보내지 않음
        api.post(f"{base}/end/")
        drop.assert_called_with(str(self.s.pk))


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
        self.assertEqual(set(data["seconds"]), {"STUDY", "BREAK", "AWAY", "AWAY_PENDING", "UNKNOWN"})
        self.assertEqual(data["actions"], {"drink_return": 2, "wave": 1, "walk_turn_walk": 0})
        self.assertEqual(len(self.api.get("/api/dashboard/weekly/").data["days"]), 7)


class PageTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("boss", password="unused-pass-5", is_staff=True)
        self.member = User.objects.create_user("mia", password="unused-pass-6")

    def test_member_pages(self):
        self.client.force_login(self.member)
        te.start(self.member)
        for url in ("/dashboard/", "/study/", "/reports/", "/analyses/"):
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
