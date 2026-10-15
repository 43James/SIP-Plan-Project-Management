"""สร้าง UserProfile ให้ผู้ใช้ที่มีอยู่แล้ว และยกเว้นไม่ต้องกรอกข้อมูลใหม่

ผู้ใช้ที่มีอยู่ก่อนฟีเจอร์นี้ใช้ระบบมาอยู่แล้ว การบังคับให้กรอกโปรไฟล์ใหม่
ทั้งหมดจะขวางการทำงานโดยไม่จำเป็น จึงตั้ง profile_completed=True ให้
ส่วนผู้ใช้ที่สมัครหลังจากนี้จะต้องกรอกตามปกติ
"""

from django.db import migrations
from django.utils import timezone


def backfill_profiles(apps, schema_editor):
    User = apps.get_model('users', 'User')
    UserProfile = apps.get_model('users', 'UserProfile')
    now = timezone.now()

    for user in User.objects.all():
        UserProfile.objects.get_or_create(user=user)

    # ยกเว้นผู้ใช้เดิมทั้งหมด (ตามที่ตกลงกับผู้ใช้งาน)
    # schema_version ตั้งเป็น 1 ให้ตรงกับ PROFILE_SCHEMA_VERSION ปัจจุบัน
    # ใช้ค่าคงที่ ไม่อ่านจาก settings เพราะ migration ต้องให้ผลเหมือนเดิมเสมอ
    User.objects.all().update(
        profile_completed=True,
        profile_completed_at=now,
        profile_schema_version=1,
    )


def reverse_backfill(apps, schema_editor):
    """ย้อนกลับได้เฉพาะสถานะ ไม่ลบ UserProfile ทิ้งเพราะจะทำข้อมูลหาย"""
    User = apps.get_model('users', 'User')
    User.objects.all().update(
        profile_completed=False,
        profile_completed_at=None,
        profile_schema_version=0,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_educationrecord_userprofile_alter_user_options_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_profiles, reverse_backfill),
    ]
