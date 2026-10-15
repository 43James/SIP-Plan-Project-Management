from django import forms
from .models import Plan, Project, ProjectTask, ProjectMember

INPUT_CLASS = 'block w-full px-4 py-2.5 rounded-xl border border-slate-200 text-slate-800 text-sm bg-slate-50 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 focus:outline-none transition'
SELECT_CLASS = 'block w-full px-4 py-2.5 rounded-xl border border-slate-200 text-slate-800 text-sm bg-slate-50 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 focus:outline-none transition'

class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ['plan_code', 'plan_name', 'fiscal_year', 'parent', 'allocated_current_budget', 'allocated_carry_over_budget', 'remarks']
        widgets = {
            'remarks': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 3, 'placeholder': 'หมายเหตุเพิ่มเติม (ถ้ามี)'}),
            'plan_code': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'เช่น P2570-001'}),
            'plan_name': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'ชื่อแผนงาน'}),
            'fiscal_year': forms.NumberInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'เช่น 2570',
                'min': '2570',   # ห้ามต่ำกว่า 2570
            }),
            'parent': forms.Select(attrs={'class': SELECT_CLASS}),
            'allocated_current_budget': forms.NumberInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': '0.00',
                'min': '0',      # ห้ามติดลบ
                'step': '0.01',
            }),
            'allocated_carry_over_budget': forms.NumberInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': '0.00',
                'min': '0',      # ห้ามติดลบ
                'step': '0.01',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Plan.objects.filter(parent__isnull=True, is_deleted=False)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields['parent'].queryset = qs

    def clean_plan_code(self):
        code = self.cleaned_data.get('plan_code', '').strip().upper()
        if not code:
            raise forms.ValidationError('กรุณากรอกรหัสแผนงาน')
        
        # ตรวจสอบว่ารหัสซ้ำกันหรือไม่
        # ถ้าเป็นการแก้ไข (instance มีอยู่แล้ว) ให้ยกเว้น record ตัวเอง
        qs = Plan.all_objects.filter(plan_code__iexact=code, is_deleted=False)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        
        if qs.exists():
            raise forms.ValidationError(
                f'รหัสแผนงาน "{code}" มีอยู่ในระบบแล้ว กรุณาใช้รหัสอื่น'
            )
        return code

    def clean_fiscal_year(self):
        year = self.cleaned_data.get('fiscal_year')
        if year is not None and year < 2570:
            raise forms.ValidationError('ปีงบประมาณต้องไม่น้อยกว่า 2570')
        return year

    def clean_allocated_current_budget(self):
        value = self.cleaned_data.get('allocated_current_budget')
        if value is not None and value < 0:
            raise forms.ValidationError('งบประมาณต้องไม่ติดลบ')
        return value

    def clean_allocated_carry_over_budget(self):
        value = self.cleaned_data.get('allocated_carry_over_budget')
        if value is not None and value < 0:
            raise forms.ValidationError('งบประมาณต้องไม่ติดลบ')
        return value

class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['plan', 'project_name', 'approval_doc_no', 'requested_current_budget', 'requested_carry_over_budget', 'start_date', 'end_date', 'is_extended', 'remarks']
        widgets = {
            'plan': forms.Select(attrs={'class': SELECT_CLASS}),
            'project_name': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'ชื่อโครงการ'}),
            'approval_doc_no': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'เลขที่เอกสาร (ถ้ามี)'}),
            'requested_current_budget': forms.NumberInput(attrs={'class': INPUT_CLASS, 'placeholder': '0.00', 'min': '0', 'step': '0.01'}),
            'requested_carry_over_budget': forms.NumberInput(attrs={'class': INPUT_CLASS, 'placeholder': '0.00', 'min': '0', 'step': '0.01'}),
            'start_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': INPUT_CLASS}),
            'end_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': INPUT_CLASS}),
            'is_extended': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500'}),
            'remarks': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 3, 'placeholder': 'หมายเหตุเพิ่มเติม (ถ้ามี)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models.functions import Length
        self.fields['plan'].queryset = Plan.objects.filter(
            parent__isnull=False,
            is_deleted=False
        ).annotate(code_len=Length('plan_code')).order_by('-fiscal_year', 'code_len', 'plan_code')

    def clean_requested_current_budget(self):
        value = self.cleaned_data.get('requested_current_budget')
        if value is not None and value < 0:
            raise forms.ValidationError('งบประมาณต้องไม่ติดลบ')
        return value

    def clean_requested_carry_over_budget(self):
        value = self.cleaned_data.get('requested_carry_over_budget')
        if value is not None and value < 0:
            raise forms.ValidationError('งบประมาณต้องไม่ติดลบ')
        return value

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date and start_date > end_date:
            self.add_error('end_date', 'วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่มต้น')
        
        return cleaned_data

class ProjectMemberForm(forms.ModelForm):
    class Meta:
        model = ProjectMember
        fields = ['user', 'responsibility', 'contribution_percent']
        widgets = {
            'user': forms.Select(attrs={'class': SELECT_CLASS}),
            'responsibility': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'หน้าที่รับผิดชอบ (เช่น หัวหน้าโครงการ, ผู้ประสานงาน)'}),
            'contribution_percent': forms.NumberInput(attrs={'class': INPUT_CLASS, 'placeholder': '100.00', 'min': '0', 'max': '100', 'step': '0.01'}),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from users.models import User
        self.fields['user'].queryset = User.objects.filter(is_active=True)

class UserChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.first_name if obj.first_name else obj.username

class ProjectTaskForm(forms.ModelForm):
    assignees = UserChoiceField(
        queryset=None,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'peer hidden'}),
        required=False
    )
    class Meta:
        model = ProjectTask
        fields = ['task_group', 'task_name', 'assignees', 'tags', 'disburse_doc_no', 'budget_source', 'amount', 'is_completed', 'disbursed_date', 'start_date', 'end_date', 'priority', 'difficulty']
        widgets = {
            'task_group': forms.Select(attrs={'class': SELECT_CLASS}),
            'task_name': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS}),
            'tags': forms.SelectMultiple(attrs={'class': 'hidden'}),
            'disburse_doc_no': forms.TextInput(attrs={'class': INPUT_CLASS}),
            'budget_source': forms.Select(attrs={'class': SELECT_CLASS}),
            'amount': forms.NumberInput(attrs={'class': INPUT_CLASS, 'placeholder': '0.00', 'min': '0', 'step': '0.01'}),
            'is_completed': forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-gray-300 text-blue-600'}),
            'disbursed_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': INPUT_CLASS}),
            'start_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': INPUT_CLASS, 'required': 'required'}),
            'end_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': INPUT_CLASS, 'required': 'required'}),
            'priority': forms.NumberInput(attrs={'type': 'range', 'min': '1', 'max': '10', 'step': '1', 'class': 'w-full h-2 rounded-lg appearance-none cursor-pointer accent-blue-600'}),
            'difficulty': forms.NumberInput(attrs={'type': 'range', 'min': '1', 'max': '10', 'step': '1', 'class': 'w-full h-2 rounded-lg appearance-none cursor-pointer accent-amber-500'}),
        }

    def __init__(self, *args, **kwargs):
        project = kwargs.pop('project', None)
        current_user = kwargs.pop('current_user', None)
        super().__init__(*args, **kwargs)
        if project:
            from users.models import User
            # Filter users to only those who are members of this project, PLUS the current user
            member_user_ids = list(project.members.values_list('user_id', flat=True))
            if current_user and current_user.id not in member_user_ids:
                member_user_ids.append(current_user.id)
            self.fields['assignees'].queryset = User.objects.filter(id__in=member_user_ids, is_active=True)
            from .models import TaskGroup, TaskTag
            self.fields['task_group'].queryset = TaskGroup.objects.filter(project=project)
            self.fields['tags'].queryset = TaskTag.objects.filter(project=project)
        else:
            from users.models import User
            self.fields['assignees'].queryset = User.objects.none()
            from .models import TaskGroup, TaskTag
            self.fields['task_group'].queryset = TaskGroup.objects.none()
            self.fields['tags'].queryset = TaskTag.objects.none()
            from .models import TaskGroup
            self.fields['task_group'].queryset = TaskGroup.objects.none()

    def clean_amount(self):
        value = self.cleaned_data.get('amount')
        if value is not None and value < 0:
            raise forms.ValidationError('จำนวนเงินต้องไม่ติดลบ')
        if value is None:
            value = 0.00
        return value

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date and start_date > end_date:
            self.add_error('end_date', 'วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่มต้น')
        return cleaned_data


class TaskCommentForm(forms.Form):
    content = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 2,
            'class': INPUT_CLASS,
            'placeholder': 'เขียนความคิดเห็น...',
        })
    )


class TaskGroupForm(forms.ModelForm):
    class Meta:
        from .models import TaskGroup
        model = TaskGroup
        fields = ['name', 'allocated_budget', 'start_date', 'end_date']
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'เช่น กิจกรรมพิจารณาคัดเลือก'}),
            'allocated_budget': forms.NumberInput(attrs={'class': INPUT_CLASS, 'placeholder': '0.00', 'min': '0', 'step': '0.01'}),
            'start_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': INPUT_CLASS, 'required': 'required'}),
            'end_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': INPUT_CLASS, 'required': 'required'}),
        }
        labels = {
            'name': 'ชื่อหัวข้อหลัก',
            'allocated_budget': 'งบประมาณ (บาท)',
            'start_date': 'วันที่เริ่มต้น',
            'end_date': 'วันที่สิ้นสุด',
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date and start_date > end_date:
            self.add_error('end_date', 'วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่มต้น')
        return cleaned_data
