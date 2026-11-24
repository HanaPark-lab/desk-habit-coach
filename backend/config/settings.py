"""Django 설정. 비밀값·주소는 환경변수로 받는다 (.env.example 참고)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# 로컬 실행용. override=True: runserver 자동 재시작(부모의 옛 환경변수 상속)에도 .env 수정이 바로 반영되게.
# Docker 컨테이너에는 이 경로에 .env 파일이 없으므로 compose가 넣은 환경변수를 건드리지 않는다.
load_dotenv(BASE_DIR.parent / ".env", override=True)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "analyses",
    "study",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("POSTGRES_DB"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ.get("POSTGRES_USER", ""),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "PORT": os.environ.get("DATABASE_PORT", "5432"),
    }}
else:
    # shortcut: POSTGRES_DB가 없으면 로컬 SQLite. Docker Compose에서는 항상 PostgreSQL을 쓴다.
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Seoul")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# 영상은 개인정보라 URL로 공개하지 않는다 (MEDIA_URL 서빙 안 함). Django·Celery가 볼륨으로 공유.
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "today"
LOGOUT_REDIRECT_URL = "login"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# 허용 카메라: 환경변수 CAMERA_<KEY>_URL → {"<key>": url}. 사용자는 key만 고른다 (임의 URL 금지, SSRF 방지).
CAMERAS = {
    k[len("CAMERA_"):-len("_URL")].lower(): v
    for k, v in os.environ.items()
    if k.startswith("CAMERA_") and k.endswith("_URL") and v
}
DEFAULT_CAPTURE_SECONDS = int(os.environ.get("DEFAULT_CAPTURE_SECONDS", "8"))
# Celery가 카메라 영상을 받을 Django 중계 주소 (Docker에서는 http://django:8000)
CAMERA_RELAY_BASE = os.environ.get("CAMERA_RELAY_BASE", "http://127.0.0.1:8000").rstrip("/")

# Celery: Redis는 작업 전달만. 결과는 Worker가 PostgreSQL에 저장하므로 result backend 없음
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_TIME_LIMIT = 600
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

FASTAPI_URL = os.environ.get("FASTAPI_URL", "http://localhost:8001").rstrip("/")
FASTAPI_TIMEOUT = int(os.environ.get("FASTAPI_TIMEOUT", "180"))

# 습관 인정 기준값. NG 영상으로 정한 뒤 .env에서 조정
DAILY_GOALS = {  # 오늘 대시보드 목표
    "STUDY_MINUTES": int(os.environ.get("STUDY_GOAL_MINUTES", "360")),
    "DRINK": 8,
    "MOVEMENT": 5,
}
# 행동 기록 기준값 (training/train_rf.py 보고서의 제안값을 .env에 반영).
# 현재 DRINK 0.56·MOVEMENT 0.64는 학습 데이터 교차검증으로 정한 초기 후보값. 별도 검증 데이터로 확정 필요.
EVENT_THRESHOLDS = {e: float(os.environ.get(f"EVENT_THRESHOLD_{e}", "0.5")) for e in ("DRINK", "MOVEMENT")}
