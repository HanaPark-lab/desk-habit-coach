from .celery import app as celery_app  # Django 시작 시 Celery 앱을 함께 로드

__all__ = ("celery_app",)
