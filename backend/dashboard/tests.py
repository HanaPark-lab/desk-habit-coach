from datetime import date, datetime, timedelta, timezone as utc_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from analyses.models import AnalysisJob
from study.models import BehaviorEvent, StudyInterval, StudySession
from study.services.time_engine import day_range

from .models import DailyUserActivity


class ReportsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("reporter")
        self.other = get_user_model().objects.create_user("other")
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.start, _ = day_range(self.today)
        clock = patch("dashboard.views.timezone.now", return_value=self.start + timedelta(hours=12))
        clock.start()
        self.addCleanup(clock.stop)

    def event(self, key, *, days=0, event_type="DRINK", action_label="drink_return", valid=True, user=None):
        return BehaviorEvent.objects.create(
            user=user or self.user, event_type=event_type, action_label=action_label, confidence=0.8,
            dedup_key=key, is_valid=valid, occurred_at=self.start + timedelta(days=days, hours=1),
        )

    def test_empty_period_and_safe_default(self):
        response = self.client.get("/reports/?period=unknown")
        self.assertEqual(response.context["period"], "7d")
        self.assertEqual(len(response.context["chart_data"]["buckets"]), 7)
        self.assertContains(response, "선택한 기간에 표시할 기록이 없습니다.", count=4)
        self.assertContains(response, "총 공부 시간")
        self.assertNotContains(response, "<canvas")

    def test_period_uses_local_dates_and_orm_counts(self):
        self.event("first-included", days=-27)
        self.event("outside", days=-28)
        self.event("future", days=1)
        self.event("daily", days=-6)
        self.event("invalid", valid=False)
        self.event("wave", event_type="MOVEMENT", action_label="wave")
        self.event("walk", event_type="MOVEMENT", action_label="walk_turn_walk")
        self.event("phone", event_type="PHONE", action_label="cell_phone")
        self.event("private", user=self.other)
        job = AnalysisJob.objects.create(user=self.user, input_type="UPLOAD", title="이전 분석 작업")
        AnalysisJob.objects.filter(pk=job.pk).update(created_at=self.start - timedelta(days=10))

        daily = self.client.get("/reports/")
        data = daily.context["chart_data"]
        self.assertEqual((len(data["buckets"]), data["drinkGoal"]), (7, 8))
        self.assertEqual(data["buckets"][0]["drink"], 1)
        self.assertEqual({key: data["totals"][key] for key in ("drink", "movement", "wave", "walk")},
                         {"drink": 1, "movement": 2, "wave": 1, "walk": 1})
        self.assertContains(daily, "정정 취소")
        self.assertContains(daily, "어깨 스트레칭")
        self.assertContains(daily, "잠깐 자리 비움")
        self.assertNotContains(daily, job.title)

        weekly = self.client.get("/reports/?period=4w")
        data = weekly.context["chart_data"]
        self.assertEqual((len(data["buckets"]), data["drinkGoal"]), (4, 56))
        self.assertEqual([bucket["drink"] for bucket in data["buckets"]], [1, 0, 0, 1])
        self.assertEqual(data["totals"]["drink"], 2)
        self.assertContains(weekly, job.title)

    def test_time_buckets_split_midnight_and_keep_sources_and_states(self):
        start = self.start - timedelta(minutes=30)
        session = StudySession.objects.create(user=self.user, status="ENDED", started_at=start)
        for state, source, first, last in (
            ("STUDY", "AUTO", -30, 30),
            ("STUDY", "MANUAL", 30, 60),
            ("BREAK", "MANUAL", 60, 70),
            ("AWAY", "AUTO", 70, 85),
            ("AWAY_PENDING", "AUTO", 85, 90),
            ("UNKNOWN", "AUTO", 90, 95),
        ):
            StudyInterval.objects.create(
                session=session, state=state, source=source,
                started_at=self.start + timedelta(minutes=first),
                ended_at=self.start + timedelta(minutes=last),
            )
        response = self.client.get("/reports/")
        data = response.context["chart_data"]
        self.assertEqual(data["buckets"][-2]["auto"], 1800)
        self.assertEqual(data["buckets"][-1]["auto"], 1800)
        self.assertEqual(
            {key: data["totals"][key] for key in ("auto", "manual", "break", "away", "unknown")},
            {"auto": 3600, "manual": 1800, "break": 600, "away": 1200, "unknown": 300},
        )
        self.assertEqual(response.context["summary"]["study"], "1시간 30분")

    def test_correction_updates_chart_data_and_cannot_change_other_users_event(self):
        own = self.event("own")
        private = self.event("private", user=self.other)
        for event, status in ((own, 200), (private, 404)):
            response = self.client.patch(
                f"/api/study/events/{event.pk}/", {"is_valid": False}, content_type="application/json",
            )
            self.assertEqual(response.status_code, status)
        response = self.client.get("/reports/?period=4w")
        self.assertEqual(response.context["chart_data"]["totals"]["drink"], 0)
        self.assertContains(response, "정정 취소")


class TodayFocusEntryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("focus-entry")
        self.client.force_login(self.user)

    def test_today_starts_manual_session_with_existing_api(self):
        dashboard = self.client.get("/dashboard/")
        self.assertContains(dashboard, "공부 시작하기")
        self.assertContains(dashboard, 'data-study-url="/study/"')
        self.assertContains(dashboard, 'data-create-url="/api/study/sessions/"')
        self.assertContains(dashboard, 'href="/reports/">기록 자세히 보기')
        self.assertContains(dashboard, "이번 주 공부 기록이 없습니다.")

        response = self.client.post("/api/study/sessions/", {"mode": "MANUAL"}, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.json()["mode"], response.json()["current_state"]), ("MANUAL", "STUDY"))
        session_id = response.json()["id"]
        self.assertEqual(self.client.get("/study/").context["open_session_id"], session_id)
        active = self.client.get("/dashboard/")
        self.assertContains(active, "공부 이어하기")
        self.assertNotContains(active, "공부 시작하기")

    def test_paused_session_is_reopened_and_creation_conflicts(self):
        opened = self.client.post("/api/study/sessions/").json()
        url = f"/api/study/sessions/{opened['id']}/"
        with patch("study.views.drop_stream"):
            paused = self.client.post(f"{url}pause/").json()
            self.assertEqual(paused["status"], "PAUSED")
            dashboard = self.client.get("/dashboard/")
            self.assertContains(dashboard, 'href="/study/">공부 이어하기')
            self.assertContains(dashboard, "휴식 중인 세션")
            self.assertEqual(self.client.get("/study/").context["open_session_id"], opened["id"])
            self.assertEqual(self.client.post("/api/study/sessions/").status_code, 409)
            self.assertEqual(StudySession.objects.filter(user=self.user).count(), 1)
            self.assertEqual(self.client.get(url).json()["current_state"], "BREAK")
            self.assertEqual(self.client.post(f"{url}end/").json()["status"], "ENDED")
        self.assertContains(self.client.get("/dashboard/"), "공부 시작하기")

    @override_settings(DAILY_GOALS={"STUDY_MINUTES": 360, "DRINK": 8, "MOVEMENT": 5})
    def test_today_summary_and_week_use_saved_time_and_events(self):
        start, _ = day_range(timezone.localdate())
        with patch("dashboard.views.timezone.now", return_value=start + timedelta(hours=3)):
            session = StudySession.objects.create(user=self.user, status="ENDED", started_at=start)
            StudyInterval.objects.create(session=session, state="STUDY", started_at=start,
                                         ended_at=start + timedelta(hours=2))
            StudyInterval.objects.create(session=session, state="BREAK", started_at=start + timedelta(hours=2),
                                         ended_at=start + timedelta(hours=2, minutes=10))
            for event_type, label in (("DRINK", "drink_return"), ("MOVEMENT", "wave")):
                BehaviorEvent.objects.create(user=self.user, event_type=event_type, action_label=label,
                                             confidence=0.8, dedup_key=label, occurred_at=start)
            dashboard = self.client.get("/dashboard/")
        self.assertContains(dashboard, "02:00:00")
        self.assertContains(dashboard, "10분")
        self.assertEqual(dashboard.context["goal_pct"], 33)
        self.assertEqual(dashboard.context["summary"]["events"]["DRINK"], 1)
        self.assertEqual(dashboard.context["summary"]["events"]["MOVEMENT"], 1)
        current = next(day for day in dashboard.context["week_data"] if day["today"])
        self.assertEqual(current["seconds"], 7200)
        self.assertContains(dashboard, "음료 섭취 감지")


@override_settings(TIME_ZONE="UTC")
class StaffUsageTests(TestCase):
    day = date(2026, 11, 24)
    midnight = datetime(2026, 11, 23, 15, tzinfo=utc_timezone.utc)

    def setUp(self):
        users = get_user_model().objects
        self.member = users.create_user("member-usage", password="local-test-usage", date_joined=self.midnight)
        self.staff = users.create_user("staff-usage", is_staff=True, date_joined=self.midnight - timedelta(days=15))

    def test_login_and_requests_are_distinct_and_deduplicated_in_seoul(self):
        previous_day = self.day - timedelta(days=1)
        with patch("django.utils.timezone.now", return_value=self.midnight - timedelta(seconds=1)):
            self.assertTrue(self.client.login(username=self.member.username, password="local-test-usage"))
            self.assertEqual(self.client.get("/dashboard/").status_code, 200)
        prior = DailyUserActivity.objects.get(user=self.member, day=previous_day)
        self.assertTrue(prior.logged_in)
        self.assertEqual(prior.last_seen_at, self.midnight - timedelta(seconds=1))

        with patch("django.utils.timezone.now", return_value=self.midnight + timedelta(seconds=1)):
            self.client.login(username=self.member.username, password="local-test-usage")
            self.client.login(username=self.member.username, password="local-test-usage")
            self.assertEqual(self.client.get("/staff/dashboard/").status_code, 403)
        current = DailyUserActivity.objects.get(user=self.member, day=self.day)
        self.assertTrue(current.logged_in)
        self.assertIsNone(current.last_seen_at)

        newest = self.midnight + timedelta(seconds=3)
        for timestamp in (newest, self.midnight + timedelta(seconds=2)):
            with patch("django.utils.timezone.now", return_value=timestamp):
                self.client.get("/reports/")
        current.refresh_from_db()
        self.assertEqual(current.last_seen_at, newest)
        self.assertEqual(DailyUserActivity.objects.filter(user=self.member, day=self.day).count(), 1)

    def test_staff_metrics_use_real_records_and_keep_missing_access_unknown(self):
        legacy_login = get_user_model().objects.create_user(
            "legacy-login", date_joined=self.midnight - timedelta(days=2), last_login=self.midnight,
        )
        visitor = get_user_model().objects.create_user("visitor", date_joined=self.midnight - timedelta(days=1))
        began = self.midnight - timedelta(minutes=30)
        DailyUserActivity.objects.create(user=self.member, day=self.day, logged_in=True, last_seen_at=self.midnight + timedelta(hours=1))
        DailyUserActivity.objects.create(user=visitor, day=self.day, last_seen_at=self.midnight + timedelta(hours=2))
        session = StudySession.objects.create(user=self.member, status="ENDED", started_at=began)
        for source, start, end in (
            ("AUTO", began, self.midnight + timedelta(minutes=30)),
            ("MANUAL", self.midnight + timedelta(minutes=30), self.midnight + timedelta(minutes=50)),
        ):
            StudyInterval.objects.create(session=session, source=source, state="STUDY", started_at=start, ended_at=end)
        job = AnalysisJob.objects.create(user=self.member, input_type="UPLOAD", status="SUCCESS")
        AnalysisJob.objects.filter(pk=job.pk).update(created_at=self.midnight)
        other_job = AnalysisJob.objects.create(user=legacy_login, input_type="UPLOAD", status="FAILURE")
        AnalysisJob.objects.filter(pk=other_job.pk).update(created_at=self.midnight + timedelta(minutes=10))

        now = self.midnight + timedelta(hours=3)
        with patch("django.utils.timezone.now", return_value=now):
            self.client.force_login(self.staff)
            response = self.client.get("/staff/dashboard/")
        usage = response.context["usage"]
        self.assertEqual(usage["total_users"], 4)
        self.assertEqual(usage["today"], {"label": "11/24", "joined": 1, "logins": 3, "visits": 2, "used": 2})
        self.assertEqual(usage["trend"][-2]["used"], 1)
        self.assertIsNone(usage["trend"][-2]["visits"])
        self.assertIsNone(usage["trend"][-2]["logins"])
        self.assertEqual([row["username"] for row in usage["visitor_rows"]], ["visitor", self.member.username])
        member = usage["visitor_rows"][1]
        self.assertEqual((member["auto_time"], member["manual_time"], member["job_count"]), ("0:30:00", "0:20:00", 1))
        legacy = next(row for row in usage["recent_users"] if row["username"] == legacy_login.username)
        self.assertIsNone(legacy["last_seen_at"])
        self.assertContains(response, "2026.11.24 01:00:00")
        self.assertContains(response, "분석 처리 성공률")
        self.assertEqual(response.context["stats"]["total"], 2)

    def test_staff_lists_are_restricted_and_admin_view_does_not_count_as_visit(self):
        self.assertEqual(self.client.get("/staff/dashboard/").status_code, 302)
        with patch("django.utils.timezone.now", return_value=self.midnight):
            self.client.force_login(self.staff)
            response = self.client.get("/staff/dashboard/")
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "오늘 수집된 접속 기록이 없습니다.")
            self.assertIsNone(DailyUserActivity.objects.get(user=self.staff, day=self.day).last_seen_at)
            self.client.force_login(self.member)
            self.assertEqual(self.client.get("/staff/dashboard/").status_code, 403)
