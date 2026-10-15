import os
from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Initialize environ
env = environ.Env(
    DJANGO_DEBUG=(bool, True)  # Default True for local development
)

# อ่านค่าจากไฟล์ .env ที่รากโปรเจ็ค (ถ้ามี) - ค่าใน environment จริงจะชนะเสมอ
_env_file = BASE_DIR / '.env'
if _env_file.exists():
    environ.Env.read_env(_env_file)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('DJANGO_SECRET_KEY', default='django-insecure-default-key-for-dev')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DJANGO_DEBUG')

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['*'])


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    
    # Google login (django-allauth)
    # ไม่ต้องใช้ django.contrib.sites เพราะตั้งค่า provider ผ่าน
    # SOCIALACCOUNT_PROVIDERS ใน settings โดยตรง
    # ถ้าวันใดเพิ่ม sites เข้ามา ต้องตั้ง SITE_ID ด้วย และห้ามสร้าง
    # SocialApp ในฐานข้อมูลซ้ำกับที่ตั้งไว้ที่นี่
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',

    # Local apps
    'users',
    'plans',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    # ต้องอยู่ท้ายสุด: ใช้ request.user (จาก AuthenticationMiddleware)
    # และใช้ messages (จาก MessageMiddleware)
    'users.middleware.ProfileCompletionMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

AUTH_USER_MODEL = 'users.User'

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

if env.bool('USE_SQLITE', default=True):
    # ห้ามวางไฟล์ .sqlite3 ไว้ในโฟลเดอร์ที่ cloud sync (Synology Drive/Dropbox/iCloud)
    # เพราะตัว sync ไม่เคารพ file lock ของ SQLite ทำให้ไฟล์พังได้
    # ตั้ง SQLITE_PATH ใน .env ให้ชี้ไปนอกโฟลเดอร์ sync เสมอ
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': env('SQLITE_PATH', default=str(BASE_DIR / 'db.sqlite3')),
            'OPTIONS': {
                # WAL: อ่าน/เขียนพร้อมกันได้ดีขึ้น และทนแอปแครช/ไฟดับกว่าเดิม
                'init_command': 'PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;',
                # ล็อกทันทีที่เริ่ม transaction ลดปัญหา "database is locked"
                'transaction_mode': 'IMMEDIATE',
                # รอคิวเขียนได้นานขึ้น (ค่าเดิมของ Django คือ 5 วินาที)
                'timeout': 20,
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': env('DB_NAME', default='sip_plan_db'),
            'USER': env('DB_USER', default='sip_user'),
            'PASSWORD': env('DB_PASSWORD', default='sippassword'),
            'HOST': env('DB_HOST', default='db'),
            'PORT': env('DB_PORT', default='3306'),
        }
    }


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'th-th'
TIME_ZONE = 'Asia/Bangkok'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Only add STATICFILES_DIRS if the directory actually exists
import os
if os.path.exists(BASE_DIR / 'static'):
    STATICFILES_DIRS = [BASE_DIR / 'static']

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# เวอร์ชันของ "ชุดฟิลด์ที่บังคับกรอก" ในโปรไฟล์
# เพิ่มค่านี้ทีละ 1 เมื่อเพิ่มฟิลด์บังคับใหม่ใน users/constants.py
# ผู้ใช้ที่เคยกรอกครบแล้วจะถูกขอให้กรอกเพิ่ม โดยไม่ต้องเขียน data migration
PROFILE_SCHEMA_VERSION = 1

# Media files (Uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ===========================================================================
# การเข้าสู่ระบบด้วยบัญชี Google (django-allauth)
# ===========================================================================

AUTHENTICATION_BACKENDS = [
    # ⚠️ ModelBackend ขาดไม่ได้ ถ้าลบออก การเข้าสู่ระบบด้วย
    #    ชื่อผู้ใช้/รหัสผ่านแบบเดิมจะพังทั้งระบบทันที
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

GOOGLE_ALLOWED_DOMAIN = env('GOOGLE_ALLOWED_DOMAIN', default='ubu.ac.th')
GOOGLE_AUTO_PROVISION = env.bool('GOOGLE_AUTO_PROVISION', default=True)

ACCOUNT_ADAPTER = 'users.adapters.NoLocalSignupAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'users.adapters.UbuGoogleSocialAccountAdapter'

ACCOUNT_LOGIN_METHODS = {'username'}
ACCOUNT_SIGNUP_FIELDS = ['username*', 'email*']
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PREVENT_ENUMERATION = True
# โปรเจ็คนี้ไม่ได้ตั้งค่า SMTP ไว้ ถ้าเปิดการยืนยันอีเมลจะพยายามส่งเมล
# ผ่าน localhost:25 แล้ว error
ACCOUNT_EMAIL_VERIFICATION = 'none'

SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_STORE_TOKENS = False      # ไม่เก็บ token ของ Google เพราะไม่ได้เรียก API แทนผู้ใช้
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
# ปุ่ม Google ต้องเป็น POST ไม่ใช่ลิงก์ GET
# เพราะ endpoint ที่ล็อกอินได้ด้วย GET เปิดช่อง login-CSRF
SOCIALACCOUNT_LOGIN_ON_GET = False

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APPS': [{
            'client_id': env('GOOGLE_OAUTH_CLIENT_ID', default=''),
            'secret': env('GOOGLE_OAUTH_CLIENT_SECRET', default=''),
            'key': '',
        }],
        'SCOPE': ['profile', 'email'],
        # ⚠️ hd ตรงนี้เป็นเพียงตัวกรองหน้าจอเลือกบัญชีของ Google
        #    กันโดเมนจริงไม่ได้ ผู้ใช้แก้ URL เองได้
        #    การตรวจจริงอยู่ใน users/adapters.py -> pre_social_login()
        'AUTH_PARAMS': {'hd': GOOGLE_ALLOWED_DOMAIN, 'prompt': 'select_account'},
        'OAUTH_PKCE_ENABLED': True,
        'FETCH_USERINFO': True,
    }
}

# ระบบจะเปิดปุ่ม Google ให้เห็นก็ต่อเมื่อตั้ง credential ครบแล้วเท่านั้น
GOOGLE_LOGIN_ENABLED = bool(
    SOCIALACCOUNT_PROVIDERS['google']['APPS'][0]['client_id']
    and SOCIALACCOUNT_PROVIDERS['google']['APPS'][0]['secret']
)

EMAIL_BACKEND = env('DJANGO_EMAIL_BACKEND',
                    default='django.core.mail.backends.console.EmailBackend')

