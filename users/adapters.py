"""Adapter ของ django-allauth — ด่านกันโดเมนสำหรับการเข้าสู่ระบบด้วย Google

หัวใจของไฟล์นี้คือ pre_social_login() ซึ่งเป็นจุดเดียวที่กันไม่ให้บัญชี
นอกโดเมน @ubu.ac.th เข้าระบบได้จริง
"""

import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

logger = logging.getLogger('users.auth')

DENY_MESSAGE = (
    'อนุญาตให้เข้าสู่ระบบด้วยบัญชีอีเมลของมหาวิทยาลัย (@{domain}) เท่านั้น '
    'กรุณาเลือกบัญชี Google ของมหาวิทยาลัย'
)
NO_ACCOUNT_MESSAGE = (
    'ยังไม่มีบัญชีผู้ใช้งานในระบบสำหรับอีเมลนี้ กรุณาติดต่อผู้ดูแลระบบ'
)
INACTIVE_MESSAGE = 'บัญชีนี้ถูกระงับการใช้งาน กรุณาติดต่อผู้ดูแลระบบ'


class NoLocalSignupAccountAdapter(DefaultAccountAdapter):
    """ปิดการสมัครสมาชิกด้วยตนเองของ allauth

    ระบบนี้สร้างบัญชีได้ 2 ทางเท่านั้น: ผู้ดูแลระบบสร้างให้
    หรือเข้าสู่ระบบด้วย Google ที่ผ่านด่านโดเมนแล้ว
    """

    def is_open_for_signup(self, request):
        return False


class UbuGoogleSocialAccountAdapter(DefaultSocialAccountAdapter):

    def _reject(self, request, message, log_detail):
        logger.warning('ปฏิเสธการเข้าสู่ระบบด้วย Google: %s', log_detail)
        messages.error(request, message)
        raise ImmediateHttpResponse(redirect('login'))

    def pre_social_login(self, request, sociallogin):
        """ด่านตรวจก่อนอนุญาตให้เข้าสู่ระบบ

        สำคัญ: AUTH_PARAMS={'hd': ...} ใน settings เป็นเพียงตัวกรอง
        หน้าจอเลือกบัญชีของ Google เท่านั้น ผู้ใช้แก้ URL เองได้
        การตรวจจริงต้องทำที่นี่ ฝั่งเซิร์ฟเวอร์
        """
        allowed = settings.GOOGLE_ALLOWED_DOMAIN.lower()

        email = (sociallogin.user.email or '').strip().lower()
        if not email:
            self._reject(request, DENY_MESSAGE.format(domain=allowed), 'ไม่มีอีเมลใน token')

        # 1) ต้องเป็นอีเมลที่ Google ยืนยันแล้วเท่านั้น
        verified = any(
            e.email.lower() == email and e.verified
            for e in sociallogin.email_addresses
        )
        if not verified:
            self._reject(request, DENY_MESSAGE.format(domain=allowed),
                         f'อีเมลยังไม่ถูกยืนยัน: {email.rsplit("@", 1)[-1]}')

        # 2) เทียบโดเมนแบบตรงตัว ห้ามใช้ endswith()
        #    เพราะ endswith('ubu.ac.th') จะรับ x@student.ubu.ac.th
        #    และ x@evil-ubu.ac.th เข้ามาด้วย
        domain = email.rsplit('@', 1)[-1] if '@' in email else ''
        if domain != allowed:
            self._reject(request, DENY_MESSAGE.format(domain=allowed),
                         f'โดเมนไม่ได้รับอนุญาต: {domain}')

        # 3) claim `hd` คือคำยืนยันจาก Google ว่าบัญชีนี้อยู่ในการดูแลของ
        #    Google Workspace โดเมนนั้นจริง (บัญชี Gmail ทั่วไปจะไม่มี claim นี้)
        #    ตรวจเมื่อมีค่ามาเท่านั้น — ถ้าไม่มี ข้อ 2 กันไปแล้ว
        hd = (sociallogin.account.extra_data.get('hd') or '').lower()
        if hd and hd != allowed:
            self._reject(request, DENY_MESSAGE.format(domain=allowed),
                         f'hd ไม่ตรงกับโดเมนที่อนุญาต: {hd}')

        # 4) บัญชีที่ถูกระงับต้องเข้าไม่ได้ แม้จะผ่านด่านโดเมนแล้ว
        if sociallogin.is_existing and not sociallogin.user.is_active:
            self._reject(request, INACTIVE_MESSAGE, f'บัญชีถูกระงับ: {sociallogin.user.pk}')

        # 5) ถ้าไม่เปิดให้สร้างบัญชีอัตโนมัติ และยังไม่มีบัญชีในระบบ
        if not sociallogin.is_existing and not settings.GOOGLE_AUTO_PROVISION:
            from .models import User
            if not User.objects.filter(email__iexact=email, is_active=True).exists():
                self._reject(request, NO_ACCOUNT_MESSAGE, f'ไม่มีบัญชีสำหรับ {domain}')

        logger.info('อนุญาตให้เข้าสู่ระบบด้วย Google โดเมน %s', domain)

    def is_open_for_signup(self, request, sociallogin):
        return settings.GOOGLE_AUTO_PROVISION

    def is_auto_signup_allowed(self, request, sociallogin):
        return settings.GOOGLE_AUTO_PROVISION

    def can_authenticate_by_email(self, login, email):
        """ควบคุมการผูกบัญชี Google เข้ากับผู้ใช้เดิมโดยดูจากอีเมล

        บัญชีสิทธิ์สูงต้องผูกด้วยมือโดยผู้ดูแลระบบเท่านั้น
        เพราะถ้าวันหนึ่งอีเมลของผู้ที่ลาออกถูกนำกลับมาใช้ซ้ำ
        เจ้าของใหม่จะได้สิทธิ์ผู้บริหารไปด้วยทันที
        """
        from .models import User

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            # ไม่มีบัญชีที่ใช้งานอยู่ตรงกับอีเมลนี้ จึงไม่มีอะไรให้ผูก
            # ผู้ใช้ใหม่จะถูกสร้างผ่านเส้นทาง auto signup แทน ไม่ใช่ทางนี้
            return False
        if user.is_superuser or user.is_staff or user.is_executive:
            logger.warning('ไม่ผูกบัญชี Google อัตโนมัติกับผู้ใช้สิทธิ์สูง: %s', user.pk)
            return False
        return super().can_authenticate_by_email(login, email)

    def populate_user(self, request, sociallogin, data):
        """เติมชื่อจากบัญชี Google ให้อัตโนมัติ เพื่อลดงานกรอกของผู้ใช้"""
        user = super().populate_user(request, sociallogin, data)
        if not user.first_name:
            user.first_name = data.get('first_name') or ''
        if not user.last_name:
            user.last_name = data.get('last_name') or ''
        # ผู้ใช้ใหม่ต้องมีบทบาทตั้งต้น ไม่งั้นจะไม่มีสิทธิ์ใด ๆ เลย
        user.is_general_staff = True
        return user
