from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib import messages

from .models import User, UserProfile

@receiver(user_logged_in)
def show_login_message(sender, user, request, **kwargs):
    name = user.get_full_name() or user.username
    messages.success(request, f'ยินดีต้อนรับเข้าสู่ระบบ, {name}!')


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """สร้าง UserProfile ให้อัตโนมัติเมื่อมีผู้ใช้ใหม่

    เงื่อนไข `if created` สำคัญมาก ถ้าไม่มี ทุกครั้งที่เรียก user.save()
    (เช่นตอนแก้สิทธิ์ใน user_permission_edit) จะยิง query ไปที่ตารางโปรไฟล์ด้วย
    """
    if created:
        UserProfile.objects.get_or_create(user=instance)
