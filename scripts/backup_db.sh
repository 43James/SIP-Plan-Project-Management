#!/bin/bash
# สำรองฐานข้อมูล SQLite ของ SIP-Plan
#
# ใช้ sqlite3 .backup ซึ่งเป็น online backup ที่ปลอดภัยแม้ระบบกำลังถูกใช้งานอยู่
# (ห้ามใช้ cp เพราะอาจได้ไฟล์ที่ก๊อปมากลางคันระหว่างเขียน)
#
# รันมือ:  ./scripts/backup_db.sh
# ตั้ง cron: ดูวิธีท้ายไฟล์นี้

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$HOME/sip-plan-data/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"

# อ่าน SQLITE_PATH จาก .env ถ้าไม่ได้ตั้งมาทาง environment
if [ -z "${SQLITE_PATH:-}" ] && [ -f "$PROJECT_DIR/.env" ]; then
    SQLITE_PATH="$(grep -E '^SQLITE_PATH=' "$PROJECT_DIR/.env" | tail -1 | cut -d= -f2-)"
fi
SQLITE_PATH="${SQLITE_PATH:-$PROJECT_DIR/db.sqlite3}"

if [ ! -f "$SQLITE_PATH" ]; then
    echo "ERROR: ไม่พบไฟล์ฐานข้อมูล: $SQLITE_PATH" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

STAMP="$(date +%Y-%m-%d_%H%M%S)"
TARGET="$BACKUP_DIR/sip-plan_$STAMP.sqlite3"

# online backup
sqlite3 "$SQLITE_PATH" ".backup '$TARGET'"

# ตรวจว่าไฟล์สำรองใช้การได้จริง ไม่ใช่แค่มีไฟล์
# journal_mode=DELETE ทำให้ไฟล์สำรองจบในตัวไฟล์เดียว ไม่มี -wal/-shm ค้าง
RESULT="$(sqlite3 "$TARGET" 'PRAGMA journal_mode=DELETE; PRAGMA integrity_check;' | tail -1)"
rm -f "$TARGET-wal" "$TARGET-shm"
if [ "$RESULT" != "ok" ]; then
    echo "ERROR: ไฟล์สำรองเสียหาย ($RESULT) - ลบทิ้ง: $TARGET" >&2
    rm -f "$TARGET"
    exit 1
fi

gzip -f "$TARGET"
chmod 600 "$TARGET.gz"

# ลบไฟล์สำรองที่เก่ากว่า KEEP_DAYS วัน
find "$BACKUP_DIR" -name 'sip-plan_*.sqlite3.gz' -type f -mtime "+$KEEP_DAYS" -delete

echo "$(date '+%Y-%m-%d %H:%M:%S') สำรองสำเร็จ: $TARGET.gz ($(du -h "$TARGET.gz" | cut -f1))"

# ---------------------------------------------------------------
# ตั้งให้รันอัตโนมัติทุกคืนตี 2:
#   crontab -e
# แล้วเพิ่มบรรทัด (แก้ path ให้ตรงกับเครื่อง):
#   0 2 * * * /bin/bash "<PROJECT_DIR>/scripts/backup_db.sh" >> "$HOME/sip-plan-data/backup.log" 2>&1
# ---------------------------------------------------------------
