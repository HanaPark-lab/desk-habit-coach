# Django 웹 서버와 Celery Worker가 함께 쓰는 이미지 (compose.yaml에서 시작 명령만 다름)
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# opencv(IP Webcam 수집)가 쓰는 시스템 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home app && mkdir -p /data/media && chown -R app /app /data
USER app

EXPOSE 8000
# gthread: 카메라 MJPEG 중계(긴 응답)가 다른 요청을 막지 않게 스레드로 처리
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--worker-class", "gthread", "--workers", "1", "--threads", "16", "--timeout", "0"]
