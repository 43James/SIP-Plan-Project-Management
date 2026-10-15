from django.db import models
from django.utils import timezone
from users.models import User
from django.db.models import Sum

class ActivePlanManager(models.Manager):
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
    all_objects = models.Manager() # Manager to access all records including deleted

    @property
    def total_projects_count(self):
        count = self.projects.count()
        for child in self.sub_plans.filter(is_deleted=False):
            count += child.projects.count()
        return count

    @property
    def completed_projects_count(self):
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
        used = ProjectTask.objects.filter(
            models.Q(project__plan=self) | models.Q(project__plan__parent=self),
            is_completed=True,
            budget_source='CURRENT'
        ).aggregate(total=Sum('amount'))['total'] or 0
        return self.allocated_current_budget - used

    @property
    def remaining_carry_over_budget(self):
        # Calculate used carry over budget from completed tasks
        used = ProjectTask.objects.filter(
            models.Q(project__plan=self) | models.Q(project__plan__parent=self),
            is_completed=True,
            budget_source='CARRY_OVER'
        ).aggregate(total=Sum('amount'))['total'] or 0
        return self.allocated_carry_over_budget - used

    def __str__(self):
        return f"{self.plan_code} - {self.plan_name}"


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

    @property
    def dynamic_status_display(self):
        tasks = self.tasks.all()
        if tasks.exists() and not tasks.filter(is_completed=False).exists():
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


class TaskGroup(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='task_groups')
    name = models.CharField(max_length=255)
    allocated_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    start_date = models.DateField()
    end_date = models.DateField()
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']

    @property
    def disbursed_amount(self):
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

