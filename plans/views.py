from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView, DetailView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy, reverse
from django.db.models import Sum, Count, Prefetch
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from users.middleware import json_endpoint
from .models import Plan, Project, ProjectTask, ProjectMember, TaskAttachment, TaskComment, TaskFollower, TaskGroup
from .forms import ProjectForm, PlanForm, ProjectTaskForm, ProjectMemberForm, TaskCommentForm, TaskGroupForm


def _task_detail_prefetch():
    """งานพร้อมของที่แนบมากับงาน

    เทมเพลตเรียก attachments.count / comments.count / tags.all ของทุกงาน
    ถ้าไม่ prefetch จะยิงคิวรีอย่างน้อย 3 ครั้งต่องานหนึ่งใบ
    """
    return Prefetch(
        'tasks',
        queryset=ProjectTask.objects.prefetch_related(
            'attachments', 'comments', 'tags', 'assignees'))


def _members_prefetch():
    """การ์ดโครงการแสดงรายชื่อสมาชิกและนับจำนวน

    ถ้าไม่ prefetch มาพร้อมผู้ใช้ จะยิงคิวรี 4 ครั้งต่อโครงการหนึ่งใบ
    (นับสมาชิก 3 ครั้ง + ดึงรายชื่อ 1 ครั้ง) แล้วตามด้วยคิวรีผู้ใช้อีกคนละครั้ง
    """
    return Prefetch('members',
                    queryset=ProjectMember.objects.select_related('user'))


class BudgetOfficerMixin(UserPassesTestMixin):
    """อนุญาตเฉพาะ Budget Officer, Executive และ Admin เท่านั้น"""
    def test_func(self):
        return self.request.user.is_budget_officer or self.request.user.is_executive or self.request.user.is_staff


class DashboardView(LoginRequiredMixin, ListView):
    model = Plan
    template_name = 'dashboard.html'
    context_object_name = 'plans'

    def get_queryset(self):
        from django.db.models.functions import Length
        qs = (
            Plan.objects.filter(is_deleted=False)
            # คำนวณจำนวนโครงการและงบคงเหลือมาพร้อมกันในคิวรีเดียว
            .with_stats()
            # เทมเพลตวน child.projects.all แล้วเรียก dynamic_status_display
            # จึงต้อง prefetch พร้อมกับ annotate สถานะงานมาด้วย
            .prefetch_related(
                Prefetch('projects', queryset=Project.objects.with_task_status())
            )
            .annotate(code_len=Length('plan_code'))
        )
        sort = self.request.GET.get('sort', 'code_asc')
        if sort == 'code_desc':
            return qs.order_by('-fiscal_year', '-code_len', '-plan_code')
        elif sort == 'id_desc':
            return qs.order_by('-id')
        elif sort == 'id_asc':
            return qs.order_by('id')
        
        # default to code_asc
        return qs.order_by('-fiscal_year', 'code_len', 'plan_code')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plans = context['plans']
        
        # ดึงเฉพาะแผนหลัก
        parent_plans = plans.filter(parent__isnull=True)
        
        # จัดเตรียมข้อมูลแผนย่อย
        children_map = {}
        for p in plans:
            if p.parent_id is not None:
                children_map.setdefault(p.parent_id, []).append(p)

        # KPI stats
        context['total_projects'] = Project.objects.filter(plan__in=plans).count()
        # งบรวม = ผลรวมของงบแผนหลักเท่านั้น (ไม่เอางบแผนย่อยมารวมซ้ำ)
        context['total_allocated'] = (
            parent_plans.aggregate(
                total=Sum('allocated_current_budget')
            )['total'] or 0
        ) + (
            parent_plans.aggregate(
                total=Sum('allocated_carry_over_budget')
            )['total'] or 0
        )
        context['total_remaining'] = sum(p.remaining_current_budget + p.remaining_carry_over_budget for p in parent_plans)
        context['current_year'] = timezone.now().year + 543  # Thai Buddhist year
        
        context['parent_plans'] = parent_plans
        context['children_map'] = children_map
        context['current_sort'] = self.request.GET.get('sort', 'code_asc')
        return context


class PlanListView(LoginRequiredMixin, BudgetOfficerMixin, ListView):
    model = Plan
    template_name = 'plans/plan_list.html'
    context_object_name = 'plans'

    def get_queryset(self):
        return Plan.objects.filter(is_deleted=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # ปีงบประมาณไทยปัจจุบัน (ค.ศ. + 543)
        from django.utils import timezone
        from django.db.models import Q
        current_thai_year = timezone.now().year + 543

        selected_year = self.request.GET.get('year', str(current_thai_year))
        search_q = self.request.GET.get('q', '').strip()

        # ดึงแผนงานทั้งหมดตามปีที่เลือก
        # เทมเพลตเรียก plan.projects.count ต่อแผน จึง prefetch มาให้
        # เมื่อ prefetch แล้ว .count จะอ่านจากแคช ไม่ยิงคิวรีใหม่
        qs = (Plan.objects.filter(is_deleted=False)
              .with_stats()
              .prefetch_related('projects'))
        if selected_year:
            qs = qs.filter(fiscal_year=selected_year)

        # ถ้ามีการค้นหา - กรองเฉพาะที่ตรง
        if search_q:
            matching = qs.filter(
                Q(plan_code__icontains=search_q) | Q(plan_name__icontains=search_q)
            )
            # รวม parent ของ sub-plan ที่ตรงด้วย
            parent_ids = matching.exclude(parent=None).values_list('parent_id', flat=True)
            qs = qs.filter(
                Q(pk__in=matching) | Q(pk__in=parent_ids)
            )

        qs = qs.order_by('plan_code')

        # สร้างโครงสร้างแบบ Tree
        parent_plans = [p for p in qs if p.parent_id is None]
        children_map = {}
        for p in qs:
            if p.parent_id is not None:
                children_map.setdefault(p.parent_id, []).append(p)

        # รายการปีงบประมาณที่มีในระบบ (สำหรับ dropdown filter)
        available_years = (
            Plan.objects.filter(is_deleted=False)
            .values_list('fiscal_year', flat=True)
            .distinct()
            .order_by('-fiscal_year')
        )

        context.update({
            'parent_plans': parent_plans,
            'children_map': children_map,
            'available_years': list(available_years),
            'selected_year': selected_year,
            'search_q': search_q,
            'current_thai_year': current_thai_year,
        })
        return context


class PlanCreateView(LoginRequiredMixin, BudgetOfficerMixin, CreateView):
    model = Plan
    form_class = PlanForm
    template_name = 'plans/plan_form.html'
    success_url = reverse_lazy('plan_list')


class PlanUpdateView(LoginRequiredMixin, BudgetOfficerMixin, UpdateView):
    model = Plan
    form_class = PlanForm
    template_name = 'plans/plan_form.html'
    success_url = reverse_lazy('plan_list')

    def get_queryset(self):
        return Plan.objects.filter(is_deleted=False)

class PlanDetailView(LoginRequiredMixin, DetailView):
    model = Plan
    template_name = 'plans/plan_detail.html'
    context_object_name = 'plan'
    
    def get_queryset(self):
        return Plan.objects.filter(is_deleted=False).with_stats()
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plan = self.object
        context['projects'] = (
            plan.projects.with_task_status()
            .select_related('plan')
            .order_by('-start_date')
        )
        if plan.parent is None:
            context['sub_plans'] = plan.sub_plans.filter(is_deleted=False).with_stats()
        return context

class ProjectFilterMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        from django.utils import timezone
        from django.db.models import Q
        
        current_thai_year = timezone.now().year + 543
        selected_year = self.request.GET.get('year', str(current_thai_year))
        search_q = self.request.GET.get('q', '').strip()
        
        if selected_year:
            qs = qs.filter(plan__fiscal_year=selected_year)
        if search_q:
            qs = qs.filter(project_name__icontains=search_q)
            
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.utils import timezone
        
        current_thai_year = timezone.now().year + 543
        selected_year = self.request.GET.get('year', str(current_thai_year))
        search_q = self.request.GET.get('q', '').strip()
        
        available_years = Plan.objects.filter(is_deleted=False).values_list('fiscal_year', flat=True).distinct().order_by('-fiscal_year')
        
        qs = getattr(self, 'queryset', None)
        if qs is None:
            qs = self.get_queryset()
            
        projects_map = {}
        plan_ids_with_projects = set()
        for proj in qs:
            plan_id = proj.plan_id
            projects_map.setdefault(plan_id, []).append(proj)
            plan_ids_with_projects.add(plan_id)
            
        all_plan_ids = set(plan_ids_with_projects)
        plans_with_projects = Plan.objects.filter(pk__in=all_plan_ids)
        parent_ids = [p.parent_id for p in plans_with_projects if p.parent_id]
        all_plan_ids.update(parent_ids)
        
        tree_plans = Plan.objects.filter(pk__in=all_plan_ids).order_by('plan_code')
        
        parent_plans = [p for p in tree_plans if p.parent_id is None]
        children_map = {}
        for p in tree_plans:
            if p.parent_id is not None:
                children_map.setdefault(p.parent_id, []).append(p)
                
        total_projects_map = {}
        for p in parent_plans:
            count = len(projects_map.get(p.pk, []))
            for child in children_map.get(p.pk, []):
                count += len(projects_map.get(child.pk, []))
            total_projects_map[p.pk] = count
        
        context.update({
            'available_years': list(available_years),
            'selected_year': selected_year,
            'search_q': search_q,
            'current_thai_year': current_thai_year,
            'parent_plans': parent_plans,
            'children_map': children_map,
            'projects_map': projects_map,
            'total_projects_map': total_projects_map,
        })
        return context

class ProjectListView(LoginRequiredMixin, ProjectFilterMixin, ListView):
    model = Project
    template_name = 'plans/project_list.html'
    context_object_name = 'projects'

    def get_queryset(self):
        qs = (Project.objects.select_related('plan', 'created_by')
              .with_task_status()
              .prefetch_related(_members_prefetch())
              .order_by('-start_date'))
        self.queryset = qs
        return super().get_queryset()

class MyProjectListView(LoginRequiredMixin, ProjectFilterMixin, ListView):
    model = Project
    template_name = 'plans/project_list.html'
    context_object_name = 'projects'

    def get_queryset(self):
        from django.db.models import Q
        qs = (Project.objects.filter(
            Q(created_by=self.request.user) | Q(members__user=self.request.user)
        ).select_related('plan', 'created_by').with_task_status()
         .prefetch_related(_members_prefetch())
         .distinct().order_by('-start_date'))
        self.queryset = qs
        return super().get_queryset()
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = "โครงการของฉัน"
        context['page_subtitle'] = "รายการโครงการที่คุณเป็นทีมงานและรับผิดชอบ"
        return context


class ProjectCreateView(LoginRequiredMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = 'project_create.html'
    success_url = reverse_lazy('dashboard')

    def get_initial(self):
        initial = super().get_initial()
        plan_pk = self.request.GET.get('plan')
        if plan_pk:
            initial['plan'] = plan_pk
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        return response

class ProjectUpdateView(LoginRequiredMixin, BudgetOfficerMixin, UpdateView):
    model = Project
    form_class = ProjectForm
    template_name = 'project_create.html'
    
    def get_success_url(self):
        return reverse('project_detail', kwargs={'pk': self.object.pk})

class ProjectDeleteView(LoginRequiredMixin, BudgetOfficerMixin, DeleteView):
    model = Project
    template_name = 'plans/project_confirm_delete.html'
    success_url = reverse_lazy('project_list')

class ProjectDetailView(LoginRequiredMixin, DetailView):
    model = Project
    template_name = 'plans/project_detail.html'
    context_object_name = 'project'

    def get_queryset(self):
        return (Project.objects
                .select_related('plan', 'created_by')
                .with_task_status()
                .prefetch_related(_task_detail_prefetch()))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # เทมเพลตวนงานแล้วเรียก attachments.count / comments.count / tags
        # ของแต่ละงาน จึงต้อง prefetch มาพร้อมกันทั้งหมด
        tasks = self.object.tasks.prefetch_related(
            'attachments', 'comments', 'tags').select_related('task_group')
        context['tasks'] = tasks
        # เทมเพลตวนงานผ่าน group.tasks.all จึงต้อง prefetch งานไว้ที่กลุ่มงาน
        # ไม่ใช่แค่ที่ context['tasks']
        context['task_groups'] = (
            self.object.task_groups
            .with_disbursed()
            .prefetch_related(_task_detail_prefetch()))
        context['members'] = self.object.members.select_related('user')
        
        completed_tasks = tasks.filter(is_completed=True)
        disbursed_current = completed_tasks.filter(budget_source='CURRENT').aggregate(total=Sum('amount'))['total'] or 0
        disbursed_carry_over = completed_tasks.filter(budget_source='CARRY_OVER').aggregate(total=Sum('amount'))['total'] or 0
        
        context['disbursed_current'] = disbursed_current
        context['remaining_current'] = self.object.requested_current_budget - disbursed_current
        
        context['disbursed_carry_over'] = disbursed_carry_over
        context['remaining_carry_over'] = self.object.requested_carry_over_budget - disbursed_carry_over
        
        context['total_requested'] = self.object.total_requested_budget
        context['total_disbursed'] = disbursed_current + disbursed_carry_over
        context['total_remaining'] = context['total_requested'] - context['total_disbursed']
        
        today = timezone.now().date()
        if self.object.start_date and self.object.end_date:
            context['total_days'] = (self.object.end_date - self.object.start_date).days
            if today > self.object.end_date:
                context['days_overdue'] = (today - self.object.end_date).days
                context['days_remaining'] = 0
            else:
                context['days_remaining'] = (self.object.end_date - today).days
                context['days_overdue'] = 0
        
        user = self.request.user
        can_edit = False
        if user.is_staff or user.is_executive or user.is_budget_officer:
            can_edit = True
        elif context['members'].filter(user=user).exists():
            can_edit = True
            
        context['can_edit'] = can_edit

        # Plan hierarchy info
        plan = self.object.plan
        context['sub_plan'] = plan
        parent_plan = plan.parent if plan.parent else plan
        context['parent_plan'] = parent_plan

        # Parent plan total allocated budget
        context['parent_allocated_current'] = parent_plan.allocated_current_budget
        context['parent_allocated_carry_over'] = parent_plan.allocated_carry_over_budget
        context['parent_allocated_total'] = parent_plan.allocated_current_budget + parent_plan.allocated_carry_over_budget

        # Sub-plan allocated budget (if it's a sub-plan)
        if plan.parent:
            context['sub_allocated_current'] = plan.allocated_current_budget
            context['sub_allocated_carry_over'] = plan.allocated_carry_over_budget
            context['sub_allocated_total'] = plan.allocated_current_budget + plan.allocated_carry_over_budget

        # Count projects under this sub-plan
        context['plan_project_count'] = plan.projects.count()

        # Total requested budget from ALL projects under this sub-plan
        from django.db.models import F
        plan_projects = plan.projects.all()
        plan_projects_budget = plan_projects.aggregate(
            total_current=Sum('requested_current_budget'),
            total_carry_over=Sum('requested_carry_over_budget')
        )
        context['plan_projects_total_current'] = plan_projects_budget['total_current'] or 0
        context['plan_projects_total_carry_over'] = plan_projects_budget['total_carry_over'] or 0
        context['plan_projects_total'] = (plan_projects_budget['total_current'] or 0) + (plan_projects_budget['total_carry_over'] or 0)

        # Remaining plan budget (allocated - sum of project requests)
        context['plan_remaining_current'] = plan.allocated_current_budget - (plan_projects_budget['total_current'] or 0)
        context['plan_remaining_carry_over'] = plan.allocated_carry_over_budget - (plan_projects_budget['total_carry_over'] or 0)

        return context

class ProjectMemberCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = ProjectMember
    form_class = ProjectMemberForm
    template_name = 'plans/project_member_form.html'
    
    def test_func(self):
        user = self.request.user
        if user.is_staff or user.is_executive or user.is_budget_officer:
            return True
        project = get_object_or_404(Project, pk=self.kwargs['pk'])
        return project.members.filter(user=user).exists()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['project'] = get_object_or_404(Project, pk=self.kwargs['pk'])
        return context
        
    def form_valid(self, form):
        form.instance.project = get_object_or_404(Project, pk=self.kwargs['pk'])
        return super().form_valid(form)
        
    def get_success_url(self):
        return reverse('project_detail', kwargs={'pk': self.kwargs['pk']})

class ProjectMemberDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = ProjectMember
    template_name = 'plans/project_member_confirm_delete.html'
    
    def test_func(self):
        user = self.request.user
        if user.is_staff or user.is_executive or user.is_budget_officer:
            return True
        member = self.get_object()
        return member.project.members.filter(user=user).exists()
    
    def get_success_url(self):
        return reverse('project_detail', kwargs={'pk': self.object.project.pk})

class ProjectTaskCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = ProjectTask
    form_class = ProjectTaskForm
    template_name = 'plans/project_task_form.html'
    
    def test_func(self):
        user = self.request.user
        if user.is_staff or user.is_executive or user.is_budget_officer:
            return True
        project = get_object_or_404(Project, pk=self.kwargs['pk'])
        return project.members.filter(user=user).exists()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['project'] = get_object_or_404(Project, pk=self.kwargs['pk'])
        return context
        
    def form_valid(self, form):
        form.instance.project = get_object_or_404(Project, pk=self.kwargs['pk'])
        return super().form_valid(form)
        
    def get_success_url(self):
        return reverse('project_task_board', kwargs={'pk': self.kwargs['pk']})

    def get_initial(self):
        initial = super().get_initial()
        group_id = self.request.GET.get('group')
        if group_id:
            initial['task_group'] = group_id
        # Pre-select the current user
        initial['assignees'] = [self.request.user.pk]
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['project'] = get_object_or_404(Project, pk=self.kwargs['pk'])
        kwargs['current_user'] = self.request.user
        return kwargs

class ProjectTaskUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = ProjectTask
    form_class = ProjectTaskForm
    template_name = 'plans/project_task_form.html'
    
    def test_func(self):
        user = self.request.user
        if user.is_staff or user.is_executive or user.is_budget_officer:
            return True
        task = self.get_object()
        return task.project.members.filter(user=user).exists()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['project'] = self.object.project
        context['attachments'] = self.object.attachments.all().order_by('-uploaded_at')
        context['comments'] = self.object.comments.all().order_by('-created_at')
        context['task_followers'] = self.object.followers.all()
        context['comment_form'] = TaskCommentForm()
        # Get project members for follower selection
        context['project_members'] = self.object.project.members.select_related('user').all()
        context['is_following'] = self.object.followers.filter(user=self.request.user).exists()
        context['follower_user_ids'] = list(self.object.followers.values_list('user_id', flat=True))
        return context
        
    def get_success_url(self):
        return reverse('project_task_board', kwargs={'pk': self.object.project.pk})
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['project'] = self.object.project
        kwargs['current_user'] = self.request.user
        return kwargs

class ProjectTaskDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = ProjectTask
    template_name = 'plans/project_task_confirm_delete.html'
    
    def test_func(self):
        user = self.request.user
        if user.is_staff or user.is_executive or user.is_budget_officer:
            return True
        task = self.get_object()
        return task.project.members.filter(user=user).exists()
    
    def get_success_url(self):
        return reverse('project_task_board', kwargs={'pk': self.object.project.pk})


@login_required
def task_attachment_upload(request, pk):
    task = get_object_or_404(ProjectTask, pk=pk)
    if request.method == 'POST' and request.FILES:
        files = request.FILES.getlist('files')
        for f in files:
            TaskAttachment.objects.create(
                task=task,
                file=f,
                file_name=f.name,
                uploaded_by=request.user
            )
        messages.success(request, f'อัปโหลด {len(files)} ไฟล์สำเร็จ')
    return redirect('project_task_edit', pk=task.pk)


@login_required
def task_attachment_delete(request, pk):
    attachment = get_object_or_404(TaskAttachment, pk=pk)
    task_pk = attachment.task.pk
    if request.method == 'POST':
        attachment.file.delete(save=False)
        attachment.delete()
        messages.success(request, 'ลบไฟล์แนบเรียบร้อย')
    return redirect('project_task_edit', pk=task_pk)


@login_required
def task_comment_create(request, pk):
    task = get_object_or_404(ProjectTask, pk=pk)
    if request.method == 'POST':
        form = TaskCommentForm(request.POST)
        if form.is_valid():
            TaskComment.objects.create(
                task=task,
                user=request.user,
                content=form.cleaned_data['content']
            )
            messages.success(request, 'เพิ่มความคิดเห็นเรียบร้อย')
    return redirect('project_task_edit', pk=task.pk)


@login_required
def task_comment_delete(request, pk):
    comment = get_object_or_404(TaskComment, pk=pk)
    task_pk = comment.task.pk
    if request.method == 'POST':
        if comment.user == request.user or request.user.is_staff:
            comment.delete()
            messages.success(request, 'ลบความคิดเห็นเรียบร้อย')
    return redirect('project_task_edit', pk=task_pk)


@login_required
def task_follower_toggle(request, pk):
    task = get_object_or_404(ProjectTask, pk=pk)
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        if user_id:
            from users.models import User
            user = get_object_or_404(User, pk=user_id)
        else:
            user = request.user
        follower, created = TaskFollower.objects.get_or_create(task=task, user=user)
        if not created:
            follower.delete()
            messages.success(request, f'ลบ {user.get_full_name() or user.username} ออกจากผู้ติดตามแล้ว')
        else:
            messages.success(request, f'เพิ่ม {user.get_full_name() or user.username} เป็นผู้ติดตามแล้ว')
    return redirect('project_task_edit', pk=task.pk)


class ProjectTaskBoardView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = Project
    template_name = 'plans/project_task_board.html'
    context_object_name = 'project'

    def test_func(self):
        user = self.request.user
        if user.is_staff or user.is_executive or user.is_budget_officer:
            return True
        project = self.get_object()
        return project.members.filter(user=user).exists()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = self.object
        # Pre-fetch all groups and their tasks to avoid N+1 queries
        # task_card.html เรียก tags กับ assignees ของทุกใบงานด้วย
        # ถ้าขาดสองตัวนี้จะกลายเป็น N+1 ต่อหนึ่งใบงานทันที
        groups = (project.task_groups
                  .with_disbursed()
                  .prefetch_related('tasks', 'tasks__attachments',
                                    'tasks__comments', 'tasks__followers',
                                    'tasks__tags', 'tasks__assignees'))
        context['task_groups'] = groups
        
        # Tasks without a group
        context['ungrouped_tasks'] = project.tasks.filter(
            task_group__isnull=True).prefetch_related(
            'attachments', 'comments', 'followers', 'tags', 'assignees')
        
        # For the add group modal
        context['group_form'] = TaskGroupForm()
        
        # Determine edit permissions
        user = self.request.user
        can_edit = False
        if user.is_staff or user.is_executive or user.is_budget_officer:
            can_edit = True
        elif project.members.filter(user=user).exists():
            can_edit = True
        context['can_edit'] = can_edit
        context['today'] = timezone.now().date()

        return context


@login_required
def task_group_create(request, project_pk):
    project = get_object_or_404(Project, pk=project_pk)
    
    # Check permissions
    user = request.user
    can_edit = user.is_staff or user.is_executive or user.is_budget_officer or project.members.filter(user=user).exists()
    if not can_edit:
        messages.error(request, 'คุณไม่มีสิทธิ์สร้างหัวข้อหลักในโครงการนี้')
        return redirect('project_task_board', pk=project.pk)

    if request.method == 'POST':
        form = TaskGroupForm(request.POST)
        if form.is_valid():
            group = form.save(commit=False)
            group.project = project
            # Auto set order to the last
            last_group = project.task_groups.order_by('-order').first()
            if last_group:
                group.order = last_group.order + 1
            group.save()
            messages.success(request, 'สร้างหัวข้อหลักใหม่เรียบร้อย')
        else:
            messages.error(request, 'ไม่สามารถสร้างหัวข้อหลักได้ กรุณาตรวจสอบว่ากรอกข้อมูลครบถ้วน')
    
    return redirect('project_task_board', pk=project.pk)


@login_required
def task_group_delete(request, pk):
    group = get_object_or_404(TaskGroup, pk=pk)
    project = group.project
    
    # Check permissions
    user = request.user
    can_edit = user.is_staff or user.is_executive or user.is_budget_officer or project.members.filter(user=user).exists()
    
    if request.method == 'POST' and can_edit:
        group.delete()
        messages.success(request, 'ลบหัวข้อหลักเรียบร้อย')
        
    return redirect('project_task_board', pk=project.pk)


@login_required
def task_group_edit(request, pk):
    group = get_object_or_404(TaskGroup, pk=pk)
    project = group.project
    
    # Check permissions
    user = request.user
    can_edit = user.is_staff or user.is_executive or user.is_budget_officer or project.members.filter(user=user).exists()
    if not can_edit:
        messages.error(request, 'คุณไม่มีสิทธิ์แก้ไขหัวข้อหลักนี้')
        return redirect('project_task_board', pk=project.pk)

    if request.method == 'POST':
        form = TaskGroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            messages.success(request, 'แก้ไขหัวข้อหลักเรียบร้อย')
            return redirect('project_task_board', pk=project.pk)
    else:
        form = TaskGroupForm(instance=group)

    return render(request, 'plans/task_group_edit.html', {
        'form': form,
        'group': group,
        'project': project,
    })

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import TaskTag

@json_endpoint
@login_required
@require_POST
def task_tag_create_api(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    # Basic permission check
    user = request.user
    can_edit = user.is_staff or user.is_executive or user.is_budget_officer or project.members.filter(user=user).exists()
    if not can_edit:
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        color = data.get('color', 'bg-slate-500 text-white').strip()
        
        if not name:
            return JsonResponse({'error': 'Name is required'}, status=400)
            
        tag = TaskTag.objects.create(project=project, name=name, color=color)
        return JsonResponse({'id': tag.id, 'name': tag.name, 'color': tag.color})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@json_endpoint
@login_required
@require_POST
def task_tag_update_api(request, tag_id):
    tag = get_object_or_404(TaskTag, pk=tag_id)
    # Check permissions
    user = request.user
    can_edit = user.is_staff or user.is_executive or user.is_budget_officer or tag.project.members.filter(user=user).exists()
    if not can_edit:
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        color = data.get('color', '').strip()
        
        if name:
            tag.name = name
        if color:
            tag.color = color
            
        tag.save()
        return JsonResponse({'id': tag.id, 'name': tag.name, 'color': tag.color})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@json_endpoint
@login_required
@require_POST
def task_tag_delete_api(request, tag_id):
    tag = get_object_or_404(TaskTag, pk=tag_id)
    # Check permissions
    user = request.user
    can_edit = user.is_staff or user.is_executive or user.is_budget_officer or tag.project.members.filter(user=user).exists()
    if not can_edit:
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    tag.delete()
    return JsonResponse({'success': True})
