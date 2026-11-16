FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PIP_RETRIES=10

WORKDIR /app

COPY call-center/requirements-runtime.txt ./call-center-requirements.txt
RUN pip install --no-cache-dir -r call-center-requirements.txt

COPY app ./app
COPY call-center ./call-center

WORKDIR /app/call-center
ENV CALLPILOT_DB_PATH=/app/call-center/data/call_center.db

EXPOSE 8020

CMD ["python", "-m", "uvicorn", "call_center_app:app", "--host", "0.0.0.0", "--port", "8020"]
