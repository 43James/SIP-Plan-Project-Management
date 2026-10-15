import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import (MaxValueValidator, MinValueValidator,
                                    RegexValidator)
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from .constants import (DEGREE_LEVEL_CHOICES, DEGREE_RANK, GENDER_CHOICES,
                        PERSONNEL_TYPE_CHOICES, PROVINCE_CHOICES,
                        REQUIRED_PROFILE_FIELDS, REQUIRED_USER_FIELDS,
                        TITLE_CHOICES, TITLE_OTHER)
from .validators import mask_national_id, validate_thai_national_id


class Department(models.Model):
    name = models.CharField(max_length=150, unique=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    """ผู้ใช้งานระบบ

    หมายเหตุสำคัญ:
    - first_name / last_name คือ "ชื่อภาษาไทย" (get_full_name() ถูกใช้ทั่วทั้ง UI)
      ส่วนชื่อภาษาอังกฤษอยู่ใน UserProfile
    - department / position อยู่ที่นี่ตั้งแต่แรกและถูกอ้างถึงใน admin,
      user_management.html และ base.html จึงไม่ย้ายไป UserProfile
    - profile_completed เป็น "แคช" ของ UserProfile.is_complete
      เก็บไว้ที่นี่เพราะ middleware อ่านทุก request และ User ถูกโหลด
      จาก session อยู่แล้ว การอ่านจึงไม่เสีย query เพิ่ม
    """

    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    position = models.CharField(max_length=150, null=True, blank=True)
    is_executive = models.BooleanField(default=False)
    is_budget_officer = models.BooleanField(default=False)
    is_finance_officer = models.BooleanField(default=False)
    is_department_head = models.BooleanField(default=False)
    is_general_staff = models.BooleanField(default=False)

    profile_completed = models.BooleanField(
        'กรอกข้อมูลส่วนตัวครบถ้วนแล้ว', default=False,
        help_text='ค่านี้เป็นแคชของ UserProfile.is_complete '
                  'หากข้อมูลเพี้ยนให้รันคำสั่ง recheck_profile_completion',
    )
    profile_completed_at = models.DateTimeField(
        'วันที่กรอกข้อมูลครบถ้วน', null=True, blank=True,
    )
    profile_schema_version = models.PositiveSmallIntegerField(
        'เวอร์ชันแบบฟอร์มที่กรอกล่าสุด', default=0,
        help_text='ใช้เทียบกับ PROFILE_SCHEMA_VERSION ใน settings '
                  'เพื่อขอให้ผู้ใช้กรอกข้อมูลเพิ่มเมื่อมีการเพิ่มฟิลด์บังคับ',
    )

    class Meta:
        constraints = [
            # กันสวมสิทธิ์: allauth ผูกบัญชี Google เข้ากับ User ที่อีเมลตรงกัน
            # ถ้ามีสองแถวอีเมลเดียวกัน มันจะหยิบแถวแรกที่ฐานข้อมูลคืนมา
            # เงื่อนไขนี้ยอมให้มีอีเมลว่างได้หลายแถว
            models.UniqueConstraint(
                Lower('email'),
                condition=~models.Q(email=''),
                name='uniq_user_email_ci',
            ),
        ]

    def __str__(self):
        return self.username


def user_photo_path(instance, filename):
    """ตั้งชื่อไฟล์รูปด้วย uuid ไม่ใช้ชื่อเดิมจากไคลเอนต์

    ชื่อไฟล์เดิมเป็นค่าที่ผู้ใช้ควบคุมได้ (เสี่ยง path traversal)
    และมักมีชื่อจริงของเจ้าของติดมาด้วย ซึ่งเป็นข้อมูลส่วนบุคคล
    """
    return f'profile_photos/{instance.user_id}/{uuid.uuid4().hex}.jpg'


class UserProfile(models.Model):
    """ข้อมูลส่วนบุคคลของผู้ใช้งาน

    แยกจาก User เพื่อ:
    1. PDPA - ลบข้อมูลส่วนบุคคลได้โดยไม่ต้องแตะบัญชีและประวัติโครงการ
       และกันไม่ให้เลขบัตรประชาชนโผล่ใน admin ของ User
    2. ประสิทธิภาพ - plans/views.py join กับ User หลายที่
       ไม่ควรลากคอลัมน์ ~20 ช่องไปด้วยทุกครั้ง
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        primary_key=True, related_name='profile', verbose_name='ผู้ใช้งาน',
    )

    # ---- ข้อมูลส่วนบุคคล ----
    title = models.CharField('คำนำหน้าชื่อ', max_length=20, choices=TITLE_CHOICES, blank=True)
    title_other = models.CharField(
        'คำนำหน้าชื่อ (ระบุเอง)', max_length=50, blank=True,
        help_text='กรอกเมื่อเลือกคำนำหน้าเป็น "อื่น ๆ"',
    )
    first_name_en = models.CharField(
        'ชื่อ (ภาษาอังกฤษ)', max_length=150, blank=True,
        validators=[RegexValidator(r"^[A-Za-z\s.'-]*$", 'กรอกเป็นภาษาอังกฤษเท่านั้น')],
    )
    last_name_en = models.CharField(
        'นามสกุล (ภาษาอังกฤษ)', max_length=150, blank=True,
        validators=[RegexValidator(r"^[A-Za-z\s.'-]*$", 'กรอกเป็นภาษาอังกฤษเท่านั้น')],
    )
    date_of_birth = models.DateField(
        'วันเดือนปีเกิด', null=True, blank=True,
        help_text='กรอกปีเป็น พ.ศ. ระบบจะแปลงให้อัตโนมัติ',
    )
    gender = models.CharField('เพศ', max_length=1, choices=GENDER_CHOICES, blank=True)

    photo = models.ImageField(
        'รูปประจำตัว', upload_to=user_photo_path, null=True, blank=True,
        help_text='ไฟล์ JPG, PNG หรือ WEBP ขนาดไม่เกิน 5 MB',
    )
    photo_thumb = models.ImageField(
        'รูปประจำตัว (ขนาดย่อ)', upload_to=user_photo_path,
        null=True, blank=True, editable=False,
    )

    # ---- เลขประจำตัวประชาชน (ข้อมูลอ่อนไหวตาม PDPA) ----
    # null=True ไม่ใช่ blank='' เพราะฟิลด์นี้ unique
    # สตริงว่างหลายแถวจะชนกัน แต่ NULL หลายแถวอยู่ร่วมกันได้
    national_id = models.CharField(
        'เลขประจำตัวประชาชน', max_length=13, null=True, blank=True, unique=True,
        validators=[validate_thai_national_id],
        help_text='ตัวเลข 13 หลัก เก็บเพื่อใช้ประกอบเอกสารเบิกจ่ายงบประมาณเท่านั้น '
                  'ระบบจะแสดงเฉพาะหลักสุดท้าย',
    )

    # ---- ข้อมูลติดต่อ ----
    mobile_phone = models.CharField(
        'โทรศัพท์มือถือ', max_length=10, blank=True,
        validators=[RegexValidator(r'^0\d{8,9}$', 'กรอกเลข 9-10 หลัก ขึ้นต้นด้วย 0')],
        help_text='ตัวเลขล้วน ไม่ต้องใส่ขีด เช่น 0812345678',
    )
    internal_extension = models.CharField(
        'เบอร์โทรภายใน', max_length=6, blank=True,
        validators=[RegexValidator(r'^\d{1,6}$', 'เบอร์ภายในต้องเป็นตัวเลข')],
    )
    # หมายเหตุความปลอดภัย: ห้ามคัดลอกค่านี้ไป User.email หรือสร้างเป็น
    # EmailAddress ของ allauth เด็ดขาด ไม่งั้นจะกลายเป็นกุญแจผูกบัญชีใบที่สอง
    # ที่ผู้ใช้ตั้งเองได้
    backup_email = models.EmailField(
        'อีเมลสำรอง', blank=True,
        help_text='ใช้สำหรับติดต่อเท่านั้น ไม่สามารถใช้เข้าสู่ระบบได้',
    )
    address = models.TextField('ที่อยู่ที่ติดต่อได้', blank=True)
    province = models.CharField('จังหวัด', max_length=50, choices=PROVINCE_CHOICES, blank=True)
    postal_code = models.CharField(
        'รหัสไปรษณีย์', max_length=5, blank=True,
        validators=[RegexValidator(r'^\d{5}$', 'รหัสไปรษณีย์ต้องเป็นตัวเลข 5 หลัก')],
    )

    # ---- ข้อมูลการปฏิบัติงาน (department / position อยู่บน User) ----
    personnel_type = models.CharField(
        'ประเภทบุคลากร', max_length=30, choices=PERSONNEL_TYPE_CHOICES, blank=True,
    )
    position_number = models.CharField('เลขที่ตำแหน่ง', max_length=30, blank=True)
    start_date = models.DateField(
        'วันที่เริ่มปฏิบัติงาน', null=True, blank=True,
        help_text='กรอกปีเป็น พ.ศ.',
    )

    # ---- ความยินยอมตาม PDPA ----
    pdpa_consent = models.BooleanField(
        'ยินยอมให้จัดเก็บข้อมูลส่วนบุคคล', default=False,
    )
    pdpa_consent_at = models.DateTimeField('วันที่ให้ความยินยอม', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ข้อมูลส่วนบุคคล'
        verbose_name_plural = 'ข้อมูลส่วนบุคคล'

    def __str__(self):
        return f'ข้อมูลส่วนบุคคลของ {self.user}'

    # ------------------------------------------------------------------
    # การแสดงผล
    # ------------------------------------------------------------------
    @property
    def display_title(self):
        """คำนำหน้าชื่อที่จะแสดงจริง รองรับกรณีเลือก "อื่น ๆ" """
        if self.title == TITLE_OTHER:
            return self.title_other
        return self.title

    @property
    def full_name_th(self):
        return f'{self.display_title}{self.user.get_full_name()}'.strip()

    @property
    def full_name_en(self):
        return f'{self.first_name_en} {self.last_name_en}'.strip()

    @property
    def masked_national_id(self):
        """เลขบัตรแบบปิดบัง - ใช้ในทุกเทมเพลตและทุกที่ที่ไม่ใช่ฟอร์มของเจ้าของ"""
        return mask_national_id(self.national_id)

    @property
    def highest_education(self):
        """วุฒิการศึกษาสูงสุด คำนวณจากรายการที่กรอกไว้

        ไม่เก็บเป็นคอลัมน์เพราะจะซ้ำซ้อนกับ EducationRecord
        และเพี้ยนทันทีที่มีคนเพิ่มวุฒิใหม่
        """
        records = list(self.user.education_records.all())
        if not records:
            return None
        return max(records, key=lambda r: DEGREE_RANK.get(r.degree_level, 0))

    # ------------------------------------------------------------------
    # ความครบถ้วนของข้อมูล
    # ------------------------------------------------------------------
    def missing_fields(self):
        """คืนรายชื่อฟิลด์ที่ยังกรอกไม่ครบ (ใช้แสดงผลและตรวจสอบ)"""
        missing = [f for f in REQUIRED_PROFILE_FIELDS if not getattr(self, f)]
        missing += [f for f in REQUIRED_USER_FIELDS if not getattr(self.user, f)]
        if not self.user.department_id:
            missing.append('department')
        return missing

    @property
    def is_complete(self):
        """แหล่งความจริงของความครบถ้วน - User.profile_completed เป็นเพียงแคช"""
        return not self.missing_fields()

    def sync_completion(self):
        """เขียนสถานะความครบถ้วนกลับไปที่ User

        ใช้ queryset.update() ไม่ใช่ user.save() เพื่อไม่ให้ทับค่าฟิลด์อื่น
        ที่อาจถูกแก้พร้อมกัน (เช่น การตั้งสิทธิ์ใน user_permission_edit)

        สำคัญ: ฟังก์ชันนี้ "ปรับขึ้นอย่างเดียว" ไม่เคยถอนสถานะที่เคยผ่านแล้ว
        เพราะผู้ใช้ที่ถูกยกเว้นไว้ตั้งแต่ migration (ผู้ใช้เดิมก่อนมีฟีเจอร์นี้)
        จะยังกรอกข้อมูลไม่ครบตามเกณฑ์ใหม่ ถ้าปล่อยให้ถอนสถานะได้
        แค่เข้าไปแก้โปรไฟล์แล้วกดบันทึกก็จะถูกบังคับให้กรอกใหม่ทั้งชุดทันที
        การขอให้กรอกเพิ่มต้องทำผ่านการเพิ่ม PROFILE_SCHEMA_VERSION เท่านั้น
        """
        if self.user.profile_completed:
            return
        if not self.is_complete:
            return

        fields = {
            'profile_completed': True,
            'profile_schema_version': settings.PROFILE_SCHEMA_VERSION,
        }
        if self.user.profile_completed_at is None:
            fields['profile_completed_at'] = timezone.now()
        User.objects.filter(pk=self.user_id).update(**fields)
        for key, value in fields.items():
            setattr(self.user, key, value)

    def save(self, *args, **kwargs):
        if self.pdpa_consent and self.pdpa_consent_at is None:
            self.pdpa_consent_at = timezone.now()
        super().save(*args, **kwargs)


class EducationRecord(models.Model):
    """ประวัติการศึกษา - หนึ่งคนมีได้หลายวุฒิ

    ผูกกับ User ไม่ใช่ UserProfile เพื่อให้ inlineformset_factory
    ผูกกับ object เดียวกับที่ฟอร์มหลักแก้ไขอยู่
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='education_records', verbose_name='ผู้ใช้งาน',
    )
    degree_level = models.CharField('ระดับการศึกษา', max_length=20, choices=DEGREE_LEVEL_CHOICES)
    degree_name = models.CharField('ชื่อปริญญา/วุฒิการศึกษา', max_length=200, blank=True)
    major = models.CharField('สาขาวิชา', max_length=200, blank=True)
    institution = models.CharField('สถาบันการศึกษา', max_length=200, blank=True)
    country = models.CharField('ประเทศ', max_length=100, default='ไทย', blank=True)
    graduation_year = models.PositiveSmallIntegerField(
        'ปีที่สำเร็จการศึกษา (พ.ศ.)', null=True, blank=True,
        # ขอบเขตแบบคงที่ ไม่ใช้ค่าที่คำนวณจากปีปัจจุบัน
        # เพราะ Django ฝัง validator ลงในไฟล์ migration
        # ถ้าใช้ค่าที่เปลี่ยนทุกปีจะเกิด migration ใหม่ทุกปีโดยไม่จำเป็น
        validators=[MinValueValidator(2400), MaxValueValidator(2700)],
        help_text='กรอกเป็นปี พ.ศ. เช่น 2560',
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'ประวัติการศึกษา'
        verbose_name_plural = 'ประวัติการศึกษา'
        ordering = ['-graduation_year', 'order']

    def __str__(self):
        return f'{self.get_degree_level_display()} - {self.major or self.institution}'
