"""ตัวตรวจสอบข้อมูล (validators) สำหรับข้อมูลโปรไฟล์ผู้ใช้งาน

ทุกตัวในไฟล์นี้ผูกไว้ที่ระดับ field ของโมเดล ไม่ใช่แค่ในฟอร์ม
เพื่อให้ทำงานทั้งในฟอร์ม, ใน Django admin และตอนเรียก full_clean()
"""

from django.core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# เลขประจำตัวประชาชน
# ---------------------------------------------------------------------------

def validate_thai_national_id(value):
    """ตรวจเลขประจำตัวประชาชนไทย 13 หลัก ด้วยสูตร mod-11

    ถ่วงน้ำหนักหลักที่ 1-12 ด้วย 13, 12, 11, ... , 2
    หลักตรวจสอบ = (11 - ผลรวม mod 11) mod 10 ต้องเท่ากับหลักที่ 13
    """
    digits = ''.join(ch for ch in str(value) if ch.isdigit())

    if len(digits) != 13:
        raise ValidationError(
            'เลขประจำตัวประชาชนต้องเป็นตัวเลข 13 หลัก',
            code='length',
        )

    # เลขซ้ำหลักเดียว เช่น 1111111111111 ผ่านสูตร mod-11 ได้
    # ซึ่งเป็นค่าที่คนมักกรอกเพื่อข้ามช่องนี้ จึงต้องกันไว้ต่างหาก
    if len(set(digits)) == 1:
        raise ValidationError(
            'เลขประจำตัวประชาชนไม่ถูกต้อง',
            code='repdigit',
        )

    total = sum(int(digits[i]) * (13 - i) for i in range(12))
    if (11 - total % 11) % 10 != int(digits[12]):
        raise ValidationError(
            'เลขประจำตัวประชาชนไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง',
            code='checksum',
        )


def normalize_national_id(value):
    """ตัดขีดและช่องว่างออก เพื่อให้ผู้ใช้วาง 1-2345-67890-12-3 ได้

    คืนค่า None เมื่อไม่มีข้อมูล เพราะฟิลด์ national_id เป็น unique
    การเก็บสตริงว่างหลายแถวจะชนกัน แต่ NULL หลายแถวอยู่ร่วมกันได้
    """
    if not value:
        return None
    digits = ''.join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def mask_national_id(value):
    """ปิดบังเลขประจำตัวประชาชน เหลือเห็นแค่หลักสุดท้าย

    ใช้แสดงผลทุกที่ ยกเว้นในฟอร์มแก้ไขของเจ้าของข้อมูลเอง
    """
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if len(digits) != 13:
        return '-'
    return f'x-xxxx-xxxxx-xx-{digits[12]}'


# ---------------------------------------------------------------------------
# รูปประจำตัว
# ---------------------------------------------------------------------------

MAX_PHOTO_BYTES = 5 * 1024 * 1024      # 5 MB
MAX_PHOTO_PIXELS = 50_000_000          # กัน decompression bomb
MIN_PHOTO_SIDE = 100                   # เล็กกว่านี้ย่อแล้วไม่เหลืออะไร
ALLOWED_PHOTO_FORMATS = {'JPEG', 'PNG', 'WEBP'}


def validate_profile_photo(f):
    """ตรวจไฟล์รูปประจำตัว 4 ชั้น

    สำคัญ: ตัดสินชนิดไฟล์จาก magic bytes ที่ Pillow อ่านได้เท่านั้น
    ไม่เชื่อนามสกุลไฟล์หรือ content_type เพราะฝั่งไคลเอนต์ปลอมได้ทั้งคู่
    ผลพลอยได้คือไฟล์ SVG ถูกปฏิเสธอัตโนมัติ (Pillow เปิดไม่ได้)
    ซึ่งจำเป็น เพราะ SVG รันจาวาสคริปต์ใน origin ของระบบเราได้
    """
    from PIL import Image

    if f.size > MAX_PHOTO_BYTES:
        raise ValidationError(
            'ไฟล์รูปต้องมีขนาดไม่เกิน 5 MB (ไฟล์ที่เลือกมีขนาด %(size).1f MB)',
            code='too_large',
            params={'size': f.size / 1024 / 1024},
        )

    pos = f.tell()
    f.seek(0)
    try:
        img = Image.open(f)
        img.verify()          # ตรวจโครงสร้างไฟล์โดยไม่ต้อง decode พิกเซล
    except ValidationError:
        raise
    except Exception:
        raise ValidationError(
            'ไฟล์รูปไม่ถูกต้องหรือเสียหาย กรุณาเลือกไฟล์ใหม่',
            code='corrupt',
        )
    finally:
        f.seek(pos)

    if img.format not in ALLOWED_PHOTO_FORMATS:
        raise ValidationError(
            'รองรับเฉพาะไฟล์ JPG, PNG และ WEBP เท่านั้น',
            code='bad_format',
        )

    width, height = img.size
    if width * height > MAX_PHOTO_PIXELS:
        raise ValidationError(
            'รูปมีขนาดภาพใหญ่เกินไป กรุณาย่อขนาดก่อนอัปโหลด',
            code='too_many_pixels',
        )
    if width < MIN_PHOTO_SIDE or height < MIN_PHOTO_SIDE:
        raise ValidationError(
            'รูปต้องมีขนาดอย่างน้อย %(min)dx%(min)d พิกเซล',
            code='too_small',
            params={'min': MIN_PHOTO_SIDE},
        )
