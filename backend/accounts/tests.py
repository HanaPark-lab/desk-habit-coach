from django.contrib.auth.models import User
from django.test import TestCase

PASSWORD = "Desk-habit-2026"


class AccountTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        r = self.client.post("/accounts/signup/", {"username": "carol", "password1": PASSWORD, "password2": PASSWORD})
        self.assertRedirects(r, "/dashboard/")
        self.assertTrue(User.objects.filter(username="carol").exists())

    def test_duplicate_username_rejected(self):
        User.objects.create_user("carol", password=PASSWORD)
        r = self.client.post("/accounts/signup/", {"username": "carol", "password1": PASSWORD, "password2": PASSWORD})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["form"].errors["username"])
        self.assertEqual(User.objects.filter(username="carol").count(), 1)

    def test_weak_password_rejected(self):
        r = self.client.post("/accounts/signup/", {"username": "dave", "password1": "1234", "password2": "1234"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="dave").exists())

    def test_analyses_page_requires_login(self):
        self.assertRedirects(self.client.get("/analyses/"), "/accounts/login/?next=/analyses/")

    def test_login_and_logout(self):
        User.objects.create_user("erin", password=PASSWORD)
        r = self.client.post("/accounts/login/", {"username": "erin", "password": PASSWORD})
        self.assertRedirects(r, "/dashboard/")
        self.assertEqual(self.client.get("/analyses/").status_code, 200)
        self.client.post("/accounts/logout/")
        self.assertEqual(self.client.get("/analyses/").status_code, 302)
