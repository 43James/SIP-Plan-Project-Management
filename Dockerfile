# syntax=docker/dockerfile:1
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=core.settings

WORKDIR /app

# psycopg[binary] มี libpq มาให้ในตัว และ Pillow มี wheel สำเร็จรูป
# จึงไม่ต้องติดตั้ง build-essential หรือ dev headers ใด ๆ เลย
# (ของเดิมติดตั้งไว้สำหรับ mysqlclient ซึ่งเลิกใช้แล้ว)
# curl มีไว้ให้ HEALTHCHECK เรียกเท่านั้น
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# ⚠️ ห้ามรันเป็น root
# UID 1000 เพื่อให้ตรงกับผู้ใช้ทั่วไปบน Linux/Synology
# ถ้าใช้ bind mount จากโฟลเดอร์แชร์บน NAS ให้ chown โฟลเดอร์นั้นเป็น 1000:1000
RUN useradd --create-home --uid 1000 sip \
    && mkdir -p /app/media /app/staticfiles \
    && chmod +x /app/scripts/*.sh \
    && chown -R sip:sip /app

USER sip

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/accounts/login/ -o /dev/null || exit 1

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["gunicorn", "core.wsgi:application"]
