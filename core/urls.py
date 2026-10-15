from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


class SIPLoginView(LoginView):
    """หน้าเข้าสู่ระบบของเรา เพิ่ม context ที่เทมเพลตต้องใช้

    ปุ่ม Google จะแสดงก็ต่อเมื่อตั้งค่า client id/secret ไว้แล้วเท่านั้น
    ไม่งั้นผู้ใช้จะกดแล้วเจอ error ของ allauth
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['google_login_enabled'] = settings.GOOGLE_LOGIN_ENABLED
        context['google_allowed_domain'] = settings.GOOGLE_ALLOWED_DOMAIN
        return context

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('plans.urls')),
    path('', include('users.urls')),
    # หน้า login ของเราเอง ต้องมาก่อน auth.urls เพื่อ override
    path('accounts/login/', SIPLoginView.as_view(), name='login'),
    # ⚠️ ลำดับสำคัญ: auth.urls ต้องมาก่อน allauth เสมอ
    #    Django จับ pattern แรกที่ตรง /accounts/login/ จึงยังเป็นหน้า login
    #    ของเราเอง ส่วน /accounts/google/... จะตกไปที่ allauth
    #    ถ้าสลับลำดับ หน้า login จะกลายเป็นเทมเพลตภาษาอังกฤษของ allauth ทันที
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/', include('allauth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
