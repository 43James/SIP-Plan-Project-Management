#!/usr/bin/env bash
# ===========================================================================
# สำรองข้อมูล SIP-Plan (PostgreSQL + ไฟล์ที่ผู้ใช้อัปโหลด)
#
# ใช้ pg_dump ซึ่งเป็น online backup ที่ปลอดภัยแม้ระบบกำลังถูกใช้งานอยู่
# ⚠️ ห้ามสำรองด้วยการคัดลอกโฟลเดอร์ข้อมูลของ Postgres ขณะระบบทำงาน
#    และห้ามพึ่ง snapshot ของ NAS เพียงอย่างเดียว
#
# รันมือ:
#   ./scripts/backup_db.sh
#
# ตั้งให้รันอัตโนมัติบน Synology:
#   Control Panel > Task Scheduler > Create > Scheduled Task > User-defined script
#   รันทุกวันตี 2 ด้วยคำสั่ง:
#     cd /volume1/docker/sip-plan && ./scripts/backup_db.sh
#
# -------------------------------- การกู้คืน --------------------------------
# ฐานข้อมูล (ทดสอบขั้นตอนนี้แล้วว่าใช้ได้จริง):
#
#   # 1. หยุดแอปก่อน ไม่งั้น connection ที่ค้างอยู่จะทำให้ DROP DATABASE ล้มเหลว
#   docker compose stop web
#
#   # 2. ตัด connection ที่เหลือค้าง แล้วสร้างฐานข้อมูลใหม่
#   docker compose exec -T db psql -U sip_user -d postgres \
#       -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity \
#           WHERE datname='sip_plan_db' AND pid<>pg_backend_pid();" \
#       -c "DROP DATABASE IF EXISTS sip_plan_db;" \
#       -c "CREATE DATABASE sip_plan_db OWNER sip_user;"
#
#   # 3. กู้ข้อมูลกลับ
#   docker compose exec -T db pg_restore -U sip_user -d sip_plan_db --no-owner \
#       < backups/sip-plan_YYYYmmdd_HHMMSS.dump
#
#   # 4. เปิดแอปกลับ
#   docker compose start web
#
# ไฟล์ media:
#   docker run --rm -v sip-plan_media:/data \
#       -v "$PWD/backups":/backup alpine \
#       sh -c "rm -rf /data/* && tar xzf /backup/media_YYYYmmdd_HHMMSS.tar.gz -C /data"
#
# ⚠️ ทดสอบการกู้คืนจริงอย่างน้อยปีละครั้ง
#    backup ที่ไม่เคยกู้คืนสำเร็จ เท่ากับไม่มี backup
# ===========================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-sip-plan}"

# อ่านเฉพาะสองค่าที่ต้องใช้จาก .env
#
# ⚠️ ห้าม source ไฟล์ .env เข้า shell (set -a; . .env)
#    เพราะ DJANGO_SECRET_KEY ที่ Django สุ่มมามีอักขระอย่าง & # $ ( ) ปนอยู่
#    shell จะตีความเป็นคำสั่งแล้ว script พังทันที (และอันตรายด้วย)
#    จึงดึงมาเฉพาะคีย์ที่ต้องใช้ แบบไม่ผ่านการตีความของ shell
read_env() {
    local key="$1" default="$2" line
    [ -f "$PROJECT_DIR/.env" ] || { printf '%s' "$default"; return; }
    line="$(grep -E "^[[:space:]]*${key}=" "$PROJECT_DIR/.env" | tail -1)" || true
    if [ -z "$line" ]; then
        printf '%s' "$default"
    else
        printf '%s' "${line#*=}"
    fi
}

DB_NAME="$(read_env POSTGRES_DB sip_plan_db)"
DB_USER="$(read_env POSTGRES_USER sip_user)"

STAMP="$(date +%Y%m%d_%H%M%S)"
DB_TARGET="$BACKUP_DIR/sip-plan_$STAMP.dump"
MEDIA_TARGET="$BACKUP_DIR/media_$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

# --- 1. ฐานข้อมูล -----------------------------------------------------------
echo "[backup] กำลัง dump ฐานข้อมูล $DB_NAME ..."
# -Fc = custom format: บีบอัดมาในตัว และ pg_restore เลือกกู้เฉพาะบางตารางได้
docker compose exec -T db \
    pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc --no-owner --no-privileges \
    > "$DB_TARGET"

if [ ! -s "$DB_TARGET" ]; then
    echo "[backup] ล้มเหลว: ไฟล์ dump ว่างเปล่า" >&2
    rm -f "$DB_TARGET"
    exit 1
fi

# ตรวจว่าไฟล์อ่านได้จริง ไม่ใช่แค่มีขนาด
echo "[backup] ตรวจสอบความสมบูรณ์ของไฟล์ dump ..."
if ! docker compose exec -T db pg_restore --list < "$DB_TARGET" > /dev/null 2>&1; then
    echo "[backup] ล้มเหลว: ไฟล์ dump เสียหาย อ่านด้วย pg_restore ไม่ได้" >&2
    rm -f "$DB_TARGET"
    exit 1
fi

TABLE_COUNT="$(docker compose exec -T db pg_restore --list < "$DB_TARGET" \
    | grep -c 'TABLE DATA' || true)"
echo "[backup] ฐานข้อมูลเรียบร้อย: $DB_TARGET ($TABLE_COUNT ตาราง)"

# --- 2. ไฟล์ที่ผู้ใช้อัปโหลด ------------------------------------------------
# ฐานข้อมูลเก็บแค่ "ชื่อไฟล์" ตัวไฟล์จริงอยู่ใน volume
# สำรองแต่ฐานข้อมูลอย่างเดียว กู้กลับมาแล้วรูปและเอกสารแนบจะหายหมด
echo "[backup] กำลังสำรองไฟล์ media ..."
docker run --rm \
    -v "${COMPOSE_PROJECT}_media":/data:ro \
    -v "$BACKUP_DIR":/backup \
    alpine tar czf "/backup/$(basename "$MEDIA_TARGET")" -C /data . 2>/dev/null

if tar tzf "$MEDIA_TARGET" > /dev/null 2>&1; then
    MEDIA_SIZE="$(du -h "$MEDIA_TARGET" | cut -f1)"
    echo "[backup] ไฟล์ media เรียบร้อย: $MEDIA_TARGET ($MEDIA_SIZE)"
else
    echo "[backup] เตือน: สำรองไฟล์ media ไม่สำเร็จ แต่ฐานข้อมูลสำรองแล้ว" >&2
    rm -f "$MEDIA_TARGET"
fi

# --- 3. ลบไฟล์เก่า ----------------------------------------------------------
find "$BACKUP_DIR" -name 'sip-plan_*.dump'  -type f -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'media_*.tar.gz'   -type f -mtime "+$KEEP_DAYS" -delete

echo "[backup] เสร็จสิ้น (เก็บย้อนหลัง $KEEP_DAYS วัน ที่ $BACKUP_DIR)"
