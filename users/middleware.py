"""บังคับให้ผู้ใช้กรอกข้อมูลส่วนตัวให้ครบก่อนใช้งานระบบ"""

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

_NAG_SESSION_KEY = '_profile_completion_nagged'


def profile_completion_exempt(view_func):
    """ยกเว้น view นี้จากการบังคับกรอกโปรไฟล์"""
    view_func.profile_completion_exempt = True
    return view_func


def json_endpoint(view_func):
    """ทำเครื่องหมายว่า view นี้ตอบเป็น JSON

    จำเป็นเพราะ fetch() ของหน้าจัดการแท็กบางตัวไม่ได้ส่ง Content-Type
    มาด้วย การเดาจาก header อย่างเดียวจึงพลาด
    """
    view_func.wants_json = True
    return view_func


class ProfileCompletionMiddleware:
    """เด้งผู้ใช้ที่ยังกรอกโปรไฟล์ไม่ครบไปหน้ากรอกข้อมูล

    ใช้ process_view ไม่ใช่ __call__ เพราะตอน __call__ ค่า
    request.resolver_match ยังเป็น None (ยังไม่ได้ resolve URL)
    ทำให้ต้องไปเทียบสตริง path ซึ่งเปราะกว่ามาก
    """

    EXEMPT_URL_NAMES = frozenset({
        'profile_setup', 'user_photo',
        'login', 'logout',
        'password_change', 'password_change_done',
        'password_reset', 'password_reset_done',
        'password_reset_confirm', 'password_reset_complete',
    })

    # /accounts/ ต้องเปิดทั้งหมด เพราะถ้าบล็อก callback ของ Google
    # ผู้ใช้จะเข้าระบบไม่ได้เลย (เกิด deadlock)
    # /admin/ เปิดไว้เป็นทางหนี ให้ผู้ดูแลเข้าไปแก้ได้ถ้าหน้ากรอกข้อมูลพัง
    EXEMPT_NAMESPACES = frozenset({'admin', 'account', 'socialaccount'})

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None

        if self._is_complete(user):
            return None

        if getattr(view_func, 'profile_completion_exempt', False):
            return None

        match = request.resolver_match
        if match is not None:
            if match.namespace in self.EXEMPT_NAMESPACES:
                return None
            if match.url_name in self.EXEMPT_URL_NAMES:
                return None

        for prefix in self._exempt_prefixes():
            if prefix and request.path_info.startswith(prefix):
                return None

        target = reverse('profile_setup')
        # ชั้นกัน redirect loop ชั้นสุดท้าย เผื่อกรณี resolver_match เป็น None
        if request.path_info == target:
            return None

        if self._wants_json(request, view_func):
            return JsonResponse(
                {'error': 'กรุณากรอกข้อมูลส่วนตัวให้ครบถ้วนก่อนใช้งานระบบ',
                 'redirect': target},
                status=403,
            )

        # แจ้งครั้งเดียวต่อ session ไม่งั้นจะมีข้อความเด้งทุกครั้งที่ถูกบล็อก
        if not request.session.get(_NAG_SESSION_KEY):
            messages.info(request, 'กรุณากรอกข้อมูลส่วนตัวให้ครบถ้วนก่อนเริ่มใช้งานระบบ')
            request.session[_NAG_SESSION_KEY] = True

        return redirect(target)

    @staticmethod
    def _is_complete(user):
        return (
            user.profile_completed
            and user.profile_schema_version >= settings.PROFILE_SCHEMA_VERSION
        )

    @staticmethod
    def _exempt_prefixes():
        return (settings.STATIC_URL, settings.MEDIA_URL, '/admin/', '/accounts/')

    @staticmethod
    def _wants_json(request, view_func):
        if getattr(view_func, 'wants_json', False):
            return True
        match = request.resolver_match
        if match is not None and (match.url_name or '').endswith('_api'):
            return True
        if request.content_type == 'application/json':
            return True
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return True
        return 'application/json' in request.headers.get('accept', '')
