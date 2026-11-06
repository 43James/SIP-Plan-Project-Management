#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# เตรียมระบบก่อนสตาร์ท gunicorn
#   1. รอให้ฐานข้อมูลพร้อมจริง ๆ (ไม่ใช่แค่พอร์ตเปิด)
#   2. migrate
#   3. collectstatic
#   4. ส่งต่อให้คำสั่งใน CMD ทำงาน
# ---------------------------------------------------------------------------
set -euo pipefail

echo "[entrypoint] รอให้ฐานข้อมูลพร้อม..."
python - <<'PY'
import os, sys, time
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.db import connections
from django.db.utils import OperationalError

ATTEMPTS = 60
for attempt in range(1, ATTEMPTS + 1):
    try:
        connections['default'].cursor()
        print('[entrypoint] ฐานข้อมูลพร้อมแล้ว')
        sys.exit(0)
    except OperationalError as exc:
        print(f'[entrypoint] ยังไม่พร้อม ({attempt}/{ATTEMPTS}): {exc}', flush=True)
        time.sleep(2)

print('[entrypoint] เชื่อมต่อฐานข้อมูลไม่สำเร็จ ยอมแพ้', file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] migrate..."
python manage.py migrate --noinput

echo "[entrypoint] collectstatic..."
python manage.py collectstatic --noinput --clear

# จำนวน worker ปรับได้จาก .env
# สูตรคร่าว ๆ คือ (2 x จำนวน core) + 1 แต่บน NAS ที่แรมจำกัดอย่าตั้งสูงเกิน
WORKERS="${GUNICORN_WORKERS:-3}"
THREADS="${GUNICORN_THREADS:-2}"
TIMEOUT="${GUNICORN_TIMEOUT:-60}"

if [ "$1" = "gunicorn" ]; then
    echo "[entrypoint] สตาร์ท gunicorn (workers=$WORKERS threads=$THREADS)"
    exec "$@" \
        --bind 0.0.0.0:8000 \
        --workers "$WORKERS" \
        --threads "$THREADS" \
        --timeout "$TIMEOUT" \
        --access-logfile - \
        --error-logfile - \
        --forwarded-allow-ips '*'
fi

exec "$@"
