"""Celery 앱. 실행 (backend 폴더에서):  celery -A config worker -l info"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")  # settings의 CELERY_* 사용
app.autodiscover_tasks()  # 각 앱의 tasks.py 탐색
