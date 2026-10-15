from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Department, EducationRecord, User, UserProfile


class CustomUserAdmin(UserAdmin):
    model = User
    fieldsets = UserAdmin.fieldsets + (
        ('RBAC Info', {'fields': ('department', 'position', 'is_executive', 'is_budget_officer',
                                  'is_finance_officer', 'is_department_head', 'is_general_staff')}),
        ('สถานะข้อมูลส่วนตัว', {'fields': ('profile_completed', 'profile_completed_at',
                                            'profile_schema_version')}),
    )
    readonly_fields = ('profile_completed_at',)
    list_display = ['username', 'email', 'department', 'position', 'is_executive',
                    'is_staff', 'profile_completed']
    list_filter = ['is_executive', 'is_budget_officer', 'is_finance_officer',
                   'is_department_head', 'is_general_staff', 'is_staff', 'is_active',
                   'department', 'profile_completed']
    search_fields = ['username', 'email', 'department__name', 'position']

    # เจตนาไม่ทำ UserProfile เป็น inline ตรงนี้
    # ถ้าทำ ผู้ใช้ที่มีสิทธิ์ is_staff ทุกคนที่แก้ไขบัญชีได้ จะเห็นเลขประจำตัว
    # ประชาชนของทุกคนไปด้วย ซึ่งกว้างเกินความจำเป็นตาม PDPA


class EducationRecordInline(admin.TabularInline):
    model = EducationRecord
    extra = 0


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """หน้าจัดการข้อมูลส่วนบุคคล แยกจาก User โดยเจตนา (ดูเหตุผลใน CustomUserAdmin)"""

    list_display = ('user', 'display_title', 'personnel_type', 'mobile_phone',
                    'masked_national_id_display')
    list_filter = ('personnel_type', 'gender', 'province', 'pdpa_consent')

    # สำคัญ: ห้ามใส่ national_id ใน search_fields
    # การค้นหาได้เท่ากับยืนยันเลขที่เดาได้ (existence oracle)
    # และคำค้นจะไปโผล่ใน access log ของเว็บเซิร์ฟเวอร์ด้วย
    search_fields = ('user__username', 'user__first_name', 'user__last_name')

    readonly_fields = ('created_at', 'updated_at', 'pdpa_consent_at',
                       'masked_national_id_display')

    @admin.display(description='เลขประจำตัวประชาชน (ปิดบัง)')
    def masked_national_id_display(self, obj):
        return obj.masked_national_id

    def get_fields(self, request, obj=None):
        fields = [f for f in super().get_fields(request, obj) if f != 'national_id']
        # เห็นเลขเต็มได้เฉพาะ superuser เท่านั้น
        # ไม่ใช้เกณฑ์ is_staff หรือ is_executive เพราะกว้างเกินไปสำหรับฟิลด์นี้
        if request.user.is_superuser:
            fields.append('national_id')
        return fields


@admin.register(EducationRecord)
class EducationRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'degree_level', 'major', 'institution', 'graduation_year')
    list_filter = ('degree_level',)
    search_fields = ('user__username', 'major', 'institution')


admin.site.register(User, CustomUserAdmin)
admin.site.register(Department)
