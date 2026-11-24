# FastAPI 추론 서버. 실시간 버퍼가 메모리에 있으므로 단일 프로세스(uvicorn 1개)로 실행한다.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# CPU 전용 PyTorch 먼저 (기본 휠은 GPU용이라 매우 큼)
RUN pip install --no-cache-dir torch==2.15.0 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# YOLO 가중치는 Git에 없으므로 빌드할 때 받아 이미지에 넣는다 (RF 모델 파일은 compose에서 읽기 전용으로 연결)
RUN mkdir -p /opt/weights && cd /opt/weights \
    && python -c "from ultralytics import YOLO; YOLO('yolo11n-pose.pt'); YOLO('yolo11n.pt')"
COPY . .
RUN useradd --create-home app && chown -R app /app
USER app
ENV POSE_WEIGHTS=/opt/weights/yolo11n-pose.pt DETECT_WEIGHTS=/opt/weights/yolo11n.pt YOLO_CONFIG_DIR=/tmp/ultralytics

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
