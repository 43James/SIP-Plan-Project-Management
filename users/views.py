from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.http import FileResponse, Http404
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import UpdateView, ListView, CreateView, DeleteView
from django.urls import reverse_lazy
from .middleware import profile_completion_exempt
from .models import User, Department, UserProfile
from .forms import (ProfileUpdateForm, ProfileSetupForm, EducationFormSet,
                    UserPermissionForm, UserCreateForm, DepartmentForm)


def _role_rows(user):
    return [
        ('Executive (ผู้บริหาร)', user.is_executive),
        ('Budget Officer (เจ้าหน้าที่งบประมาณ)', user.is_budget_officer),
        ('Finance Officer (เจ้าหน้าที่การเงิน)', user.is_finance_officer),
        ('Department Head (หัวหน้าแผนก)', user.is_department_head),
        ('General Staff (พนักงานทั่วไป)', user.is_general_staff),
    ]


def _get_profile(user):
    """ดึงโปรไฟล์แบบกันพัง

    ปกติ signal สร้างให้อยู่แล้วตอนสร้างผู้ใช้ และ migration backfill
    ให้ผู้ใช้เดิมครบแล้ว แต่กัน edge case ไว้ เช่น superuser ที่ถูกสร้าง
    ด้วยวิธีอื่น หรือแถวที่ถูกลบไปด้วยมือ
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


# เลขประจำตัวประชาชนต้องไม่โผล่ในหน้า debug ของ Django
# (DJANGO_DEBUG ค่าเริ่มต้นเป็น True ซึ่งจะแสดง POST body ทั้งก้อน)
@sensitive_post_parameters('national_id', 'date_of_birth')
@login_required
def profile_view(request):
    profile = _get_profile(request.user)
    if request.method == 'POST':
        # ต้องส่ง request.FILES ด้วย ไม่งั้นรูปที่อัปโหลดจะหายไปเงียบ ๆ
        form = ProfileUpdateForm(request.POST, request.FILES, instance=profile)
        formset = EducationFormSet(request.POST, instance=request.user)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            profile.sync_completion()
            messages.success(request, 'บันทึกข้อมูลส่วนตัวเรียบร้อยแล้ว')
            return redirect('profile')
        messages.error(request, 'บันทึกไม่สำเร็จ กรุณาตรวจสอบข้อมูลที่กรอก')
    else:
        form = ProfileUpdateForm(instance=profile)
        formset = EducationFormSet(instance=request.user)

    return render(request, 'users/profile.html', {
        'form': form,
        'formset': formset,
        'profile': profile,
        'roles': _role_rows(request.user),
    })


@sensitive_post_parameters('national_id', 'date_of_birth')
@profile_completion_exempt
@login_required
def profile_setup_view(request):
    """หน้ากรอกข้อมูลส่วนตัวครั้งแรก

    ต้องมี @profile_completion_exempt ไม่งั้น middleware จะเด้งหน้านี้
    กลับมาที่ตัวเอง เกิด redirect loop
    """
    profile = _get_profile(request.user)

    # กรอกครบแล้วไม่ต้องเข้าหน้านี้อีก
    if request.user.profile_completed:
        return redirect('dashboard')

    if request.method == 'POST':
        form = ProfileSetupForm(request.POST, request.FILES, instance=profile)
        formset = EducationFormSet(request.POST, instance=request.user)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            # save() เรียก sync_completion ให้แล้ว แต่ formset อาจเพิ่งบันทึก
            # ประวัติการศึกษาเข้ามา จึงคำนวณซ้ำอีกรอบ
            profile.sync_completion()
            messages.success(request, 'บันทึกข้อมูลเรียบร้อยแล้ว ยินดีต้อนรับเข้าสู่ระบบ')
            return redirect('dashboard')
        messages.error(request, 'ยังกรอกข้อมูลไม่ครบ กรุณาตรวจสอบช่องที่มีเครื่องหมายสีแดง')
    else:
        form = ProfileSetupForm(instance=profile)
        formset = EducationFormSet(instance=request.user)

    return render(request, 'users/profile_setup.html', {
        'form': form,
        'formset': formset,
        'profile': profile,
    })


@profile_completion_exempt
@login_required
def user_photo(request, pk):
    """เสิร์ฟรูปประจำตัวผ่าน Django แทนการเปิด /media/ ให้เข้าถึงตรง ๆ

    เหตุผลสองข้อ:
    1. core/urls.py เสิร์ฟ /media/ เฉพาะตอน DEBUG=True พอขึ้น production
       จริงรูปจะ 404 ทุกหน้า
    2. รูปบุคลากรเป็นข้อมูลส่วนบุคคล ไม่ควรเปิดให้คนนอกระบบเข้าถึงได้

    ถ้าปริมาณโหลดมากขึ้นจนเป็นปัญหา เปลี่ยนไปใช้ X-Accel-Redirect
    ของ nginx ได้โดยแก้แค่ header ในฟังก์ชันนี้
    """
    profile = get_object_or_404(UserProfile.objects.only('photo', 'photo_thumb'), user_id=pk)
    field = profile.photo_thumb if request.GET.get('size') == 'thumb' else profile.photo
    if not field:
        raise Http404('ไม่มีรูปประจำตัว')

    response = FileResponse(field.open('rb'), content_type='image/jpeg')
    response['Cache-Control'] = 'private, max-age=300'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_staff or self.request.user.is_executive


class UserManagementView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = User
    template_name = 'users/user_management.html'
    context_object_name = 'users'

    def get_queryset(self):
        # select_related('profile') จำเป็น เพราะเทมเพลตแสดงรูปประจำตัวทุกแถว
        # ถ้าไม่มี จะเกิด N+1 หนึ่ง query ต่อหนึ่งผู้ใช้
        return User.objects.select_related('profile', 'department').order_by('username')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Attach role_fields to each user for template rendering
        for u in context['users']:
            u.role_fields = [
                u.is_executive,
                u.is_budget_officer,
                u.is_finance_officer,
                u.is_department_head,
                u.is_general_staff,
            ]
        return context


class UserCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = 'users/user_create.html'
    success_url = reverse_lazy('user_management')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"เพิ่มผู้ใช้งาน {self.object.username} เรียบร้อยแล้ว สามารถตั้งค่าสิทธิ์ให้ผู้ใช้งานต่อได้ทันที")
        # Redirect to permission edit for convenience
        return redirect('user_permission_edit', pk=self.object.pk)


@login_required
def user_permission_edit(request, pk):
    if not (request.user.is_staff or request.user.is_executive):
        messages.error(request, 'คุณไม่มีสิทธิ์ดำเนินการนี้')
        return redirect('dashboard')

    edited_user = get_object_or_404(User, pk=pk)
    perm_fields = [
        ('System Admin (ผู้ดูแลระบบสูงสุด)', 'is_superuser'),
        ('Executive (ผู้บริหาร)', 'is_executive'),
        ('Budget Officer (เจ้าหน้าที่งบประมาณ)', 'is_budget_officer'),
        ('Finance Officer (เจ้าหน้าที่การเงิน)', 'is_finance_officer'),
        ('Department Head (หัวหน้าแผนก)', 'is_department_head'),
        ('General Staff (พนักงานทั่วไป)', 'is_general_staff'),
    ]

    if request.method == 'POST':
        # ถ้าเป็น System Admin จะได้สิทธิ์ is_staff ด้วยอัตโนมัติเพื่อให้เข้าหน้า /admin ได้
        is_admin = 'is_superuser' in request.POST
        edited_user.is_superuser = is_admin
        edited_user.is_staff = is_admin
        
        edited_user.is_executive = 'is_executive' in request.POST
        edited_user.is_budget_officer = 'is_budget_officer' in request.POST
        edited_user.is_finance_officer = 'is_finance_officer' in request.POST
        edited_user.is_department_head = 'is_department_head' in request.POST
        edited_user.is_general_staff = 'is_general_staff' in request.POST
        edited_user.save()
        messages.success(request, f'อัปเดตสิทธิ์ของ {edited_user.get_full_name() or edited_user.username} เรียบร้อยแล้ว')
        return redirect('user_management')

    return render(request, 'users/user_permission_edit.html', {
        'edited_user': edited_user,
        'perm_fields': perm_fields,
    })

# --- Department Management ---

class DepartmentListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = Department
    template_name = 'users/department_list.html'
    context_object_name = 'departments'
    ordering = ['name']

class DepartmentCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Department
    form_class = DepartmentForm
    template_name = 'users/department_form.html'
    success_url = reverse_lazy('department_list')

    def form_valid(self, form):
        messages.success(self.request, f"เพิ่มกลุ่มงาน {form.cleaned_data['name']} เรียบร้อยแล้ว")
        return super().form_valid(form)

class DepartmentUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Department
    form_class = DepartmentForm
    template_name = 'users/department_form.html'
    success_url = reverse_lazy('department_list')

    def form_valid(self, form):
        messages.success(self.request, f"แก้ไขกลุ่มงานเป็น {form.cleaned_data['name']} เรียบร้อยแล้ว")
        return super().form_valid(form)

class DepartmentDeleteView(LoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = Department
    template_name = 'users/department_confirm_delete.html'
    success_url = reverse_lazy('department_list')

    def delete(self, request, *args, **kwargs):
        department = self.get_object()
        # Check if any user uses this department
        if User.objects.filter(department=department).exists():
            messages.error(request, f"ไม่สามารถลบ {department.name} ได้เนื่องจากมีผู้ใช้งานอยู่ในกลุ่มงานนี้")
            return redirect('department_list')
            
        messages.success(request, f"ลบกลุ่มงาน {department.name} เรียบร้อยแล้ว")
        return super().delete(request, *args, **kwargs)
