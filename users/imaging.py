"""ประมวลผลรูปประจำตัว

ทุกภาพที่อัปโหลดจะถูก decode และ encode ใหม่เสมอ ไม่เก็บไฟล์ต้นฉบับ
เพราะการ re-encode คือสิ่งที่พิสูจน์ว่าไฟล์ที่เก็บเป็นรูปภาพจริง
ไม่ใช่ไฟล์ polyglot ที่เป็นได้ทั้งรูปและสคริปต์
"""

import io
import uuid

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

PHOTO_SIZE = (512, 512)
THUMB_SIZE = (96, 96)
JPEG_QUALITY = 85


def _render(img, size):
    """ครอปเป็นสี่เหลี่ยมจัตุรัสแล้วย่อ คืนค่าเป็น ContentFile ของ JPEG"""
    # centering ทางตั้งเยื้องขึ้นเล็กน้อย เพราะใบหน้ามักอยู่ค่อนไปทางบนของภาพ
    fitted = ImageOps.fit(img, size, Image.LANCZOS, centering=(0.5, 0.4))
    buf = io.BytesIO()
    fitted.save(buf, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return ContentFile(buf.getvalue())


def process_profile_photo(profile, uploaded):
    """แปลงไฟล์ที่อัปโหลดเป็นรูปประจำตัวขนาดเต็มและขนาดย่อ

    ต้องเรียกหลังจากผ่าน validate_profile_photo แล้วเท่านั้น
    ฟังก์ชันนี้ไม่ได้ save() ตัว profile ผู้เรียกต้อง save เอง
    """
    uploaded.seek(0)
    img = Image.open(uploaded)

    # รูปจากมือถือมักเก็บทิศทางไว้ใน EXIF แทนที่จะหมุนพิกเซลจริง
    # ถ้าไม่แก้ตรงนี้ รูปจะแสดงตะแคง
    img = ImageOps.exif_transpose(img)

    # convert('RGB') ทำสองอย่าง: แบนชั้นโปร่งใสเพื่อบันทึกเป็น JPEG ได้
    # และทิ้ง EXIF ทั้งหมดรวมถึงพิกัด GPS ซึ่งเป็นผลดีตาม PDPA
    # เพราะบุคลากรมักอัปโหลดรูปถ่ายจากมือถือที่ติดพิกัดบ้านมาด้วย
    img = img.convert('RGB')

    stem = uuid.uuid4().hex
    profile.photo.save(f'{stem}.jpg', _render(img, PHOTO_SIZE), save=False)
    profile.photo_thumb.save(f'{stem}_thumb.jpg', _render(img, THUMB_SIZE), save=False)


def delete_photo_files(profile):
    """ลบไฟล์รูปปัจจุบันของโปรไฟล์ออกจากดิสก์ และล้างค่าในฟิลด์"""
    for field in (profile.photo, profile.photo_thumb):
        if field:
            field.delete(save=False)


def delete_photo_names(profile, names):
    """ลบไฟล์ตามชื่อที่ระบุ

    ต้องใช้วิธีนี้ตอนเปลี่ยนรูป เพราะ ModelForm.save(commit=False)
    เขียนไฟล์ใหม่ทับฟิลด์ photo ไปแล้ว การอ่าน profile.photo ตอนนั้น
    จะได้ไฟล์ใหม่ ไม่ใช่ไฟล์เก่าที่ต้องการลบ ผลคือไฟล์เก่าค้างในดิสก์
    """
    storage = profile.photo.storage
    for name in names:
        if name and storage.exists(name):
            storage.delete(name)
