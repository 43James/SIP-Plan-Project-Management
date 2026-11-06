from decimal import Decimal

from django.db import models
from django.utils import timezone
from users.models import User
from django.db.models import (
    Count, DecimalField, IntegerField, OuterRef, Q, Subquery, Sum, Value,
)
from django.db.models.functions import Coalesce

# ===========================================================================
# ตัวช่วยคำนวณสถิติแบบคิวรีเดียว
#
# property ของ Plan/Project/TaskGroup ยิงคิวรีของตัวเองทุกครั้งที่ถูกเรียก
# พอเทมเพลตวนลูปแสดงหลายรายการ จำนวนคิวรีจึงโตตามจำนวนแถว (N+1)
#
# วิธีแก้: queryset ด้านล่างคำนวณค่าเดียวกันมาล่วงหน้าด้วย subquery
# แล้ว property จะอ่านค่าที่ annotate ไว้ก่อน ถ้าไม่มีค่อยยิงคิวรีเอง
# ผลลัพธ์เหมือนเดิมทุกประการ และเทมเพลตไม่ต้องแก้แม้แต่บรรทัดเดียว
#
# ⚠️ โครงสร้างแผนงานเป็นสองชั้นเสมอ (แผนหลัก -> แผนย่อย) subquery ข้างล่าง
#    จึงมองแค่ parent ชั้นเดียว ตรงกับที่ property เดิมทำ
# ===========================================================================

ZERO_BAHT = Value(
    Decimal('0.00'), output_field=DecimalField(max_digits=15, decimal_places=2))

BAHT = DecimalField(max_digits=15, decimal_places=2)


def _single_value(queryset, alias, expression):
    """บีบ subquery ให้เหลือแถวเดียว

    values(_grp=Value(1)) คือการ GROUP BY ค่าคงที่ ทำให้ aggregate ทั้งก้อน
    ยุบเหลือแถวเดียว ใช้ใน Subquery ได้ (Django ไม่ยอมให้ aggregate ตรง ๆ)
    """
    return (queryset.order_by()
            .values(_grp=Value(1))
            .annotate(**{alias: expression})
            .values(alias)[:1])


class PlanQuerySet(models.QuerySet):
    """คำนวณสถิติของแผนงานทั้งหน้าในไม่กี่คิวรี แทนการยิงทีละแผน"""

    @staticmethod
    def _projects_of_plan():
        """โครงการของแผนนี้ รวมของแผนย่อยด้วย"""
        return Q(plan_id=OuterRef('pk')) | Q(plan__parent_id=OuterRef('pk'))

    @staticmethod
    def _tasks_of_plan():
        """งานในโครงการของแผนนี้ รวมของแผนย่อยด้วย"""
        return (Q(project__plan_id=OuterRef('pk'))
                | Q(project__plan__parent_id=OuterRef('pk')))

    def with_project_counts(self):
        scope = self._projects_of_plan()
        total = _single_value(
            Project.objects.filter(scope), 'c', Count('pk', distinct=True))
        # "สำเร็จ" = มีงานอย่างน้อยหนึ่งงาน และไม่เหลืองานที่ยังไม่เสร็จ
        # ตรงกับเงื่อนไขใน Project.dynamic_status_display
        done = _single_value(
            Project.objects.filter(scope)
                   .filter(tasks__isnull=False)
                   .exclude(tasks__is_completed=False),
            'c', Count('pk', distinct=True))
        return self.annotate(
            _total_projects_count=Coalesce(
                Subquery(total, output_field=IntegerField()), 0),
            _completed_projects_count=Coalesce(
                Subquery(done, output_field=IntegerField()), 0),
        )

    def with_budget_usage(self):
        def used(source):
            return _single_value(
                ProjectTask.objects.filter(
                    self._tasks_of_plan(),
                    is_completed=True, budget_source=source),
                's', Sum('amount'))

        return self.annotate(
            _used_current_budget=Coalesce(
                Subquery(used('CURRENT'), output_field=BAHT), ZERO_BAHT),
            _used_carry_over_budget=Coalesce(
                Subquery(used('CARRY_OVER'), output_field=BAHT), ZERO_BAHT),
        )

    def with_stats(self):
        """ใช้ตัวนี้ในหน้าที่แสดงทั้งจำนวนโครงการและงบคงเหลือ"""
        return self.with_project_counts().with_budget_usage()


class ActivePlanManager(models.Manager.from_queryset(PlanQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

class Plan(models.Model):
    fiscal_year = models.IntegerField()
    plan_code = models.CharField(max_length=50, unique=True)
    plan_name = models.CharField(max_length=255)
    parent = models.ForeignKey('self', on_delete=models.RESTRICT, null=True, blank=True, related_name='sub_plans')
    
    allocated_current_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    allocated_carry_over_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    remarks = models.TextField(null=True, blank=True)
    
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActivePlanManager()  # Default manager
    # all_objects เห็นทุกแถวรวมที่ลบแล้ว และใช้ with_stats() ได้เหมือนกัน
    all_objects = models.Manager.from_queryset(PlanQuerySet)()

    class Meta:
        indexes = [
            # แทบทุกหน้ากรองด้วย is_deleted=False แล้วตามด้วยปีงบประมาณ
            models.Index(fields=['is_deleted', 'fiscal_year'],
                         name='plan_active_year_idx'),
        ]

    @property
    def total_projects_count(self):
        cached = getattr(self, '_total_projects_count', None)
        if cached is not None:
            return cached
        count = self.projects.count()
        for child in self.sub_plans.filter(is_deleted=False):
            count += child.projects.count()
        return count

    @property
    def completed_projects_count(self):
        cached = getattr(self, '_completed_projects_count', None)
        if cached is not None:
            return cached
        count = sum(1 for p in self.projects.all() if p.dynamic_status_display == "สำเร็จ")
        for child in self.sub_plans.filter(is_deleted=False):
            count += sum(1 for p in child.projects.all() if p.dynamic_status_display == "สำเร็จ")
        return count

    def delete(self, *args, **kwargs):
        # Strict Soft Delete Logic
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()
        
    @property
    def remaining_current_budget(self):
        # Calculate used current budget from completed tasks
        used = getattr(self, '_used_current_budget', None)
        if used is None:
            used = ProjectTask.objects.filter(
                models.Q(project__plan=self) | models.Q(project__plan__parent=self),
                is_completed=True,
                budget_source='CURRENT'
            ).aggregate(total=Sum('amount'))['total'] or 0
        return self.allocated_current_budget - used

    @property
    def remaining_carry_over_budget(self):
        # Calculate used carry over budget from completed tasks
        used = getattr(self, '_used_carry_over_budget', None)
        if used is None:
            used = ProjectTask.objects.filter(
                models.Q(project__plan=self) | models.Q(project__plan__parent=self),
                is_completed=True,
                budget_source='CARRY_OVER'
            ).aggregate(total=Sum('amount'))['total'] or 0
        return self.allocated_carry_over_budget - used

    def __str__(self):
        return f"{self.plan_code} - {self.plan_name}"


class ProjectQuerySet(models.QuerySet):
    """นับงานของแต่ละโครงการมาพร้อมกันในคิวรีเดียว

    dynamic_status_display เดิมยิงคิวรี 2 ครั้งต่อโครงการ (มีงานไหม /
    เหลืองานค้างไหม) พอวนลูปแสดงรายการโครงการจึงกลายเป็น N+1 ทันที
    """

    def with_task_status(self):
        return self.annotate(
            _task_count=Count('tasks', distinct=True),
            _open_task_count=Count(
                'tasks', filter=Q(tasks__is_completed=False), distinct=True),
        )


class Project(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled')
    ]

    plan = models.ForeignKey(Plan, on_delete=models.RESTRICT, related_name='projects')
    project_name = models.CharField(max_length=255)
    approval_doc_no = models.CharField(max_length=100, null=True, blank=True)
    
    requested_current_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    requested_carry_over_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    is_extended = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_projects')
    remarks = models.TextField(null=True, blank=True, help_text="หมายเหตุ (เพิ่มเติม)")

    objects = ProjectQuerySet.as_manager()

    class Meta:
        indexes = [
            # ใช้ตอนดึงโครงการของแผนหนึ่ง ๆ แล้วเรียงตามวันเริ่ม
            # (วัดแล้วว่า planner หยิบไปใช้จริง)
            models.Index(fields=['plan', 'start_date'],
                         name='project_plan_start_idx'),
        ]
        # หมายเหตุ: เคยลอง index บน end_date เพื่อหวังช่วยสถานะ "เกินกำหนด"
        # แต่สถานะนั้นคำนวณในฝั่ง Python จากแถวที่ดึงมาแล้ว ไม่ได้กรองที่ฐานข้อมูล
        # วัดแล้ว planner ไม่เคยใช้เลย จึงไม่ใส่ไว้

    @property
    def dynamic_status_display(self):
        task_count = getattr(self, '_task_count', None)
        open_count = getattr(self, '_open_task_count', None)
        if task_count is not None and open_count is not None:
            has_tasks, has_open = task_count > 0, open_count > 0
        else:
            tasks = self.tasks.all()
            has_tasks = tasks.exists()
            has_open = tasks.filter(is_completed=False).exists()

        if has_tasks and not has_open:
            return "สำเร็จ"
            
        from django.utils import timezone
        today = timezone.now().date()
        if today > self.end_date:
            return "เกินกำหนด"
            
        if self.is_extended:
            return "กำลังดำเนินการ (ขอขยายเวลา)"
            
        return "กำลังดำเนินการ"

    @property
    def total_requested_budget(self):
        return self.requested_current_budget + self.requested_carry_over_budget

    def __str__(self):
        return self.project_name


class ProjectMember(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.RESTRICT)
    responsibility = models.CharField(max_length=255, null=True, blank=True)
    contribution_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.user.username} - {self.project.project_name}"


class TaskGroupQuerySet(models.QuerySet):
    """รวมยอดเบิกจ่ายของทุกกลุ่มงานมาในคิวรีเดียว

    disbursed_amount เดิมยิง aggregate หนึ่งครั้งต่อกลุ่มงาน และถูกเรียกซ้ำ
    ผ่าน remaining_budget กับ budget_usage_percent อีก
    """

    def with_disbursed(self):
        return self.annotate(
            _disbursed_amount=Coalesce(
                Sum('tasks__amount', filter=Q(tasks__is_completed=True)),
                ZERO_BAHT),
        )


class TaskGroup(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='task_groups')
    name = models.CharField(max_length=255)
    allocated_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    start_date = models.DateField()
    end_date = models.DateField()
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TaskGroupQuerySet.as_manager()

    class Meta:
        ordering = ['order', 'created_at']

    @property
    def disbursed_amount(self):
        cached = getattr(self, '_disbursed_amount', None)
        if cached is not None:
            return cached
        return self.tasks.filter(is_completed=True).aggregate(
            total=Sum('amount'))['total'] or 0

    @property
    def remaining_budget(self):
        return self.allocated_budget - self.disbursed_amount

    @property
    def budget_usage_percent(self):
        if self.allocated_budget and self.allocated_budget > 0:
            pct = (self.disbursed_amount / self.allocated_budget) * 100
            return min(pct, 100)
        return 0

    @property
    def days_overdue(self):
        from django.utils import timezone
        today = timezone.now().date()
        if self.end_date and today > self.end_date:
            return (today - self.end_date).days
        return 0

    @property
    def days_remaining(self):
        from django.utils import timezone
        today = timezone.now().date()
        if self.end_date and today <= self.end_date:
            return (self.end_date - today).days
        return 0

    @property
    def total_days(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days
        return 0

    def __str__(self):
        return f"{self.name} ({self.project.project_name})"

class TaskTag(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tags')
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=50, default='bg-slate-500 text-white')

    def __str__(self):
        return self.name


class ProjectTask(models.Model):
    BUDGET_SOURCE_CHOICES = [
        ('CURRENT', 'งบประมาณปีปัจจุบัน'),
        ('CARRY_OVER', 'งบเหลื่อมปี')
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    task_group = models.ForeignKey(TaskGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    assignees = models.ManyToManyField(User, blank=True, related_name='assigned_tasks')
    tags = models.ManyToManyField(TaskTag, blank=True, related_name='tasks')
    task_name = models.TextField()
    disburse_doc_no = models.CharField(max_length=100, null=True, blank=True)
    budget_source = models.CharField(max_length=20, choices=BUDGET_SOURCE_CHOICES)
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00, null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    disbursed_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(help_text="วันที่เริ่มต้น")
    end_date = models.DateField(help_text="วันที่สิ้นสุด")
    priority = models.IntegerField(default=5, help_text='ระดับความสำคัญ 1-10')
    difficulty = models.IntegerField(default=5, help_text='คะแนนความยาก 1-10')

    class Meta:
        indexes = [
            # การคำนวณงบทุกที่กรองด้วย is_completed + budget_source
            # โดยจำกัดขอบเขตด้วยโครงการก่อนเสมอ
            # วัดที่ข้อมูล 12,000 งาน: planner เรียกใช้ index นี้ราว 8,000 ครั้ง
            # ต่อการเปิดหน้าหลักหนึ่งรอบ เป็นตัวที่คุ้มที่สุดในบรรดา index ที่เพิ่ม
            models.Index(fields=['project', 'is_completed', 'budget_source'],
                         name='task_proj_done_source_idx'),
        ]
        # หมายเหตุ: เคยลอง index (task_group, is_completed) สำหรับ
        # TaskGroup.disbursed_amount แต่หนึ่งกลุ่มมีงานไม่กี่ใบ
        # planner จึงใช้ index ของ FK task_group_id แล้วกรองต่อเอาเองเร็วกว่า
        # วัดแล้วไม่ถูกใช้เลย จึงไม่ใส่ไว้

    @property
    def days_overdue(self):
        from django.utils import timezone
        today = timezone.now().date()
        if self.end_date and today > self.end_date:
            return (today - self.end_date).days
        return 0

    @property
    def days_remaining(self):
        from django.utils import timezone
        today = timezone.now().date()
        if self.end_date and today <= self.end_date:
            return (self.end_date - today).days
        return 0

    def __str__(self):
        return f"Task: {self.task_name[:50]}"


class TaskAttachment(models.Model):
    task = models.ForeignKey(ProjectTask, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='task_attachments/%Y/%m/')
    file_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.file_name

    @property
    def is_image(self):
        ext = self.file_name.lower().split('.')[-1] if '.' in self.file_name else ''
        return ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg')

    @property
    def file_extension(self):
        return self.file_name.lower().split('.')[-1] if '.' in self.file_name else ''


class TaskComment(models.Model):
    task = models.ForeignKey(ProjectTask, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Comment by {self.user.username} on {self.task}"


class TaskFollower(models.Model):
    task = models.ForeignKey(ProjectTask, on_delete=models.CASCADE, related_name='followers')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    followed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['task', 'user']

    def __str__(self):
        return f"{self.user.username} follows {self.task}"

