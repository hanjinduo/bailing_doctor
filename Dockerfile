# 百灵医生 · 后端镜像（SQLite / PostgreSQL 均可运行）
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PORT=8010

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8010/api/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8010"]
