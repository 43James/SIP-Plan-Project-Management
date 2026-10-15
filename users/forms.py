import datetime
import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.forms import inlineformset_factory

from .constants import TITLE_OTHER
from .imaging import delete_photo_files, delete_photo_names, process_profile_photo
from .models import Department, EducationRecord, User, UserProfile
from .validators import (normalize_national_id, validate_profile_photo,
                         validate_thai_national_id)

INPUT_CLASS = 'block w-full px-4 py-2.5 rounded-xl border border-slate-200 text-slate-800 text-sm bg-slate-50 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 focus:outline-none transition'
CHECKBOX_CLASS = 'w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-2 focus:ring-blue-100'

# ปีเกิดที่เป็นไปได้ ใช้กันกรณีกรอกปี ค.ศ. มาทั้งที่ระบบคาดหวัง พ.ศ.
_MIN_CE_YEAR = 1900


class ThaiDateField(forms.DateField):
    """ช่องวันที่ที่รับปี พ.ศ. และเก็บลงฐานข้อมูลเป็น ค.ศ.

    จำเป็นเพราะ Django ไม่รองรับพุทธศักราช และ date(2510, 1, 1)
    เป็นค่าที่ถูกต้องตามหลักของ Python จึงจะไม่ error แต่ข้อมูลเพี้ยนเงียบ ๆ
    ถ้าไม่ดักแปลงตรงนี้

    ต่างจาก Plan.fiscal_year ที่เก็บ พ.ศ. ตรง ๆ ได้ เพราะอันนั้นเป็น
    IntegerField ไม่ใช่ DateField
    """

    def to_python(self, value):
        date = super().to_python(value)
        if date is None:
            return None
        if date.year > 2400:          # เป็น พ.ศ. แน่นอน
            date = date.replace(year=date.year - 543)
        if date.year < _MIN_CE_YEAR:
            raise forms.ValidationError('ปีไม่ถูกต้อง กรุณากรอกปีเป็น พ.ศ. เช่น 2530')
        if date > datetime.date.today():
            raise forms.ValidationError('วันที่ต้องไม่เกินวันปัจจุบัน')
        return date

    def prepare_value(self, value):
        """แสดงกลับเป็น พ.ศ. ตอน render ฟอร์ม"""
        if isinstance(value, datetime.date):
            return value.replace(year=value.year + 543).isoformat()
        return value


class _ProfileFieldsMixin:
    """ตรรกะที่ใช้ร่วมกันระหว่างฟอร์มกรอกครั้งแรกและฟอร์มแก้ไขโปรไฟล์"""

    def clean_national_id(self):
        """ตัดขีดออกก่อน แล้วค่อยตรวจ checksum

        ต้องตรวจเองตรงนี้ เพราะเราประกาศฟิลด์ในฟอร์มเอง (max_length กว้างกว่า
        ของโมเดล เพื่อรับรูปแบบที่มีขีด) validator ของโมเดลจึงไม่ถูกเรียก
        """
        value = normalize_national_id(self.cleaned_data.get('national_id'))
        if value:
            validate_thai_national_id(value)
        return value

    def clean_mobile_phone(self):
        """ตัดขีดและช่องว่างออกก่อน แล้วค่อยตรวจรูปแบบ

        ลำดับสำคัญ: ถ้าปล่อยให้ max_length ของโมเดล (10) ตรวจก่อน
        ค่าอย่าง 081-234-5678 จะถูกปฏิเสธเพราะยาว 12 ตัวอักษร
        """
        value = (self.cleaned_data.get('mobile_phone') or '').replace('-', '').replace(' ', '')
        if value and not re.fullmatch(r'0\d{8,9}', value):
            raise forms.ValidationError('กรอกเบอร์โทรศัพท์ 9-10 หลัก ขึ้นต้นด้วย 0')
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('title') == TITLE_OTHER and not cleaned.get('title_other'):
            self.add_error('title_other', 'กรุณาระบุคำนำหน้าชื่อ')
        return cleaned

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        # ตรวจเฉพาะตอนที่มีไฟล์ใหม่ถูกอัปโหลดมาจริง ๆ
        # ค่าที่เป็น FieldFile คือรูปเดิมที่ยังไม่ถูกเปลี่ยน
        if photo and hasattr(photo, 'file') and hasattr(photo, 'content_type'):
            validate_profile_photo(photo)
        return photo

    def _remember_old_photos(self):
        """เก็บชื่อไฟล์รูปเดิมไว้ตั้งแต่ตอนสร้างฟอร์ม

        ต้องทำที่นี่ เพราะเมื่อถึงขั้น save() ค่า instance.photo จะถูก
        ModelForm เขียนทับด้วยไฟล์ที่เพิ่งอัปโหลดไปแล้ว
        """
        self._old_photo_names = (self.instance.photo.name, self.instance.photo_thumb.name)

    def _save_photo(self, profile):
        photo = self.cleaned_data.get('photo')
        if photo and hasattr(photo, 'content_type'):
            process_profile_photo(profile, photo)
            delete_photo_names(profile, getattr(self, '_old_photo_names', ()))
        elif photo is False:
            # ผู้ใช้ติ๊ก "ล้างรูป" ใน ClearableFileInput
            delete_photo_files(profile)


def _thai_date_widget(label):
    return forms.DateInput(
        attrs={'class': INPUT_CLASS, 'type': 'date', 'placeholder': label},
        format='%Y-%m-%d',
    )


class ProfileSetupForm(_ProfileFieldsMixin, forms.ModelForm):
    """ฟอร์มกรอกข้อมูลส่วนตัวครั้งแรก

    รวมฟิลด์จากสองโมเดล: UserProfile เป็นหลัก และฟิลด์ที่อยู่บน User
    (ชื่อ นามสกุล หน่วยงาน ตำแหน่ง) ประกาศเพิ่มเข้ามา
    """

    first_name = forms.CharField(
        label='ชื่อ (ภาษาไทย)', max_length=150,
        widget=forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'สมชาย'}),
    )
    last_name = forms.CharField(
        label='นามสกุล (ภาษาไทย)', max_length=150,
        widget=forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'ใจดี'}),
    )
    department = forms.ModelChoiceField(
        label='กลุ่มงาน/แผนก', queryset=Department.objects.all(),
        empty_label='--- เลือกกลุ่มงาน/แผนก ---', required=False,
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )
    position = forms.CharField(
        label='ตำแหน่ง', max_length=150,
        widget=forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'นักวิเคราะห์นโยบายและแผน'}),
    )

    date_of_birth = ThaiDateField(
        label='วันเดือนปีเกิด', required=False, widget=_thai_date_widget('วันเดือนปีเกิด'),
        help_text='กรอกปีเป็น พ.ศ.',
    )
    start_date = ThaiDateField(
        label='วันที่เริ่มปฏิบัติงาน', required=False, widget=_thai_date_widget('วันที่เริ่มปฏิบัติงาน'),
        help_text='กรอกปีเป็น พ.ศ.',
    )

    # ประกาศสองฟิลด์นี้เองเพื่อให้ max_length กว้างพอรับรูปแบบที่มีขีด
    # การตรวจค่าจริงอยู่ใน clean_* ของ _ProfileFieldsMixin ซึ่งทำงานหลังตัดขีดแล้ว
    mobile_phone = forms.CharField(
        label='โทรศัพท์มือถือ', max_length=20, required=False,
        help_text='ตัวเลขล้วน ไม่ต้องใส่ขีด เช่น 0812345678',
        widget=forms.TextInput(attrs={
            'class': INPUT_CLASS, 'placeholder': '0812345678', 'inputmode': 'tel',
        }),
    )
    national_id = forms.CharField(
        label='เลขประจำตัวประชาชน', max_length=20, required=False,
        help_text='ตัวเลข 13 หลัก เก็บเพื่อใช้ประกอบเอกสารเบิกจ่ายงบประมาณเท่านั้น '
                  'ระบบจะแสดงเฉพาะหลักสุดท้าย',
        widget=forms.TextInput(attrs={
            'class': INPUT_CLASS, 'placeholder': '1234567890123',
            'inputmode': 'numeric', 'autocomplete': 'off', 'maxlength': '20',
        }),
    )

    class Meta:
        model = UserProfile
        fields = [
            'title', 'title_other', 'first_name_en', 'last_name_en',
            'date_of_birth', 'gender', 'photo',
            'national_id',
            'mobile_phone', 'internal_extension', 'backup_email',
            'address', 'province', 'postal_code',
            'personnel_type', 'position_number', 'start_date',
            'pdpa_consent',
        ]
        widgets = {
            'title': forms.Select(attrs={'class': INPUT_CLASS}),
            'title_other': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'ระบุคำนำหน้า'}),
            'first_name_en': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Somchai'}),
            'last_name_en': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Jaidee'}),
            'gender': forms.Select(attrs={'class': INPUT_CLASS}),
            'photo': forms.ClearableFileInput(attrs={
                'class': 'block w-full text-sm text-slate-600 file:mr-3 file:py-2 file:px-4 '
                         'file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-700 '
                         'file:text-sm file:font-semibold hover:file:bg-blue-100',
                'accept': 'image/jpeg,image/png,image/webp',
            }),
            'national_id': forms.TextInput(attrs={
                'class': INPUT_CLASS, 'placeholder': '1234567890123',
                'inputmode': 'numeric', 'autocomplete': 'off', 'maxlength': '17',
            }),
            'mobile_phone': forms.TextInput(attrs={
                'class': INPUT_CLASS, 'placeholder': '0812345678', 'inputmode': 'tel',
            }),
            'internal_extension': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': '1234'}),
            'backup_email': forms.EmailInput(attrs={'class': INPUT_CLASS}),
            'address': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 3}),
            'province': forms.Select(attrs={'class': INPUT_CLASS}),
            'postal_code': forms.TextInput(attrs={
                'class': INPUT_CLASS, 'placeholder': '34190', 'inputmode': 'numeric',
            }),
            'personnel_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'position_number': forms.TextInput(attrs={'class': INPUT_CLASS}),
            'pdpa_consent': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._remember_old_photos()
        user = self.instance.user
        self.fields['first_name'].initial = user.first_name
        self.fields['last_name'].initial = user.last_name
        self.fields['department'].initial = user.department_id
        self.fields['position'].initial = user.position

        # ฟิลด์บังคับตาม REQUIRED_PROFILE_FIELDS ใน constants.py
        for name in ('title', 'mobile_phone'):
            self.fields[name].required = True
        self.fields['pdpa_consent'].required = True
        self.fields['pdpa_consent'].label = (
            'ข้าพเจ้ายินยอมให้มหาวิทยาลัยอุบลราชธานีจัดเก็บและใช้ข้อมูลส่วนบุคคลข้างต้น '
            'เพื่อการบริหารงานบุคคลและการเบิกจ่ายงบประมาณ'
        )

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.department = self.cleaned_data['department']
        user.position = self.cleaned_data['position']

        self._save_photo(profile)
        if commit:
            user.save(update_fields=['first_name', 'last_name', 'department', 'position'])
            profile.save()
            profile.sync_completion()
        return profile


class ProfileUpdateForm(ProfileSetupForm):
    """ฟอร์มแก้ไขโปรไฟล์จากหน้า "ข้อมูลส่วนตัว"

    สืบทอดฟิลด์ทั้งหมดจาก ProfileSetupForm ต่างกันแค่ไม่บังคับติ๊ก
    ความยินยอม PDPA ซ้ำ เพราะผู้ใช้อาจเข้ามาแก้แค่บางช่อง

    ความปลอดภัย: ไม่มีฟิลด์ email โดยเจตนา
    ระบบผูกบัญชี Google เข้ากับผู้ใช้ที่อีเมลตรงกัน ถ้าผู้ใช้แก้อีเมลตัวเองได้
    จะตั้งเป็นอีเมลของเพื่อนร่วมงานแล้วรอให้เพื่อนเข้าระบบครั้งแรกได้
    อีเมลจึงแก้ได้เฉพาะผู้ดูแลระบบ
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pdpa_consent'].required = False


class EducationRecordForm(forms.ModelForm):
    class Meta:
        model = EducationRecord
        fields = ['degree_level', 'degree_name', 'major', 'institution', 'graduation_year']
        widgets = {
            'degree_level': forms.Select(attrs={'class': INPUT_CLASS}),
            'degree_name': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'วิทยาศาสตรบัณฑิต'}),
            'major': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'สาขาวิชา'}),
            'institution': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'สถาบันการศึกษา'}),
            'graduation_year': forms.NumberInput(attrs={
                'class': INPUT_CLASS, 'placeholder': '2560', 'inputmode': 'numeric',
            }),
        }

    def clean_graduation_year(self):
        year = self.cleaned_data.get('graduation_year')
        if year:
            current_thai_year = datetime.date.today().year + 543
            if year > current_thai_year:
                raise forms.ValidationError(
                    f'ปีที่สำเร็จการศึกษาต้องไม่เกินปีปัจจุบัน (พ.ศ. {current_thai_year})'
                )
        return year


EducationFormSet = inlineformset_factory(
    User, EducationRecord, form=EducationRecordForm,
    extra=1, can_delete=True,
)


class UserPermissionForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['is_executive', 'is_budget_officer', 'is_finance_officer',
                  'is_department_head', 'is_general_staff']


class UserCreateForm(UserCreationForm):
    department = forms.ModelChoiceField(
        queryset=Department.objects.all(),
        empty_label='--- เลือกกลุ่มงาน/แผนก ---',
        required=False,
        widget=forms.Select(attrs={'class': INPUT_CLASS})
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'department', 'position')
        widgets = {
            'username': forms.TextInput(attrs={'class': INPUT_CLASS}),
            'email': forms.EmailInput(attrs={'class': INPUT_CLASS}),
            'first_name': forms.TextInput(attrs={'class': INPUT_CLASS}),
            'last_name': forms.TextInput(attrs={'class': INPUT_CLASS}),
            'position': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'ตำแหน่ง'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            if field not in self.Meta.widgets:
                self.fields[field].widget.attrs.update({'class': INPUT_CLASS})


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'ชื่อกลุ่มงาน/แผนก'}),
        }
