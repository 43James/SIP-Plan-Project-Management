from django.contrib import admin
from .models import Plan, Project, ProjectMember, ProjectTask

class PlanAdmin(admin.ModelAdmin):
    list_display = ['plan_code', 'plan_name', 'fiscal_year', 'allocated_current_budget', 'allocated_carry_over_budget', 'is_deleted']
    list_filter = ['fiscal_year', 'is_deleted']
    search_fields = ['plan_code', 'plan_name']

class ProjectAdmin(admin.ModelAdmin):
    list_display = ['project_name', 'plan', 'status', 'start_date', 'end_date', 'requested_current_budget', 'requested_carry_over_budget']
    list_filter = ['status', 'start_date']
    search_fields = ['project_name', 'approval_doc_no']

class ProjectMemberAdmin(admin.ModelAdmin):
    list_display = ['project', 'user', 'responsibility', 'contribution_percent']
    list_filter = ['project']
    search_fields = ['user__username', 'project__project_name']

class ProjectTaskAdmin(admin.ModelAdmin):
    list_display = ['task_name', 'project', 'budget_source', 'amount', 'is_completed', 'disbursed_date']
    list_filter = ['budget_source', 'is_completed', 'disbursed_date']
    search_fields = ['task_name', 'disburse_doc_no']

admin.site.register(Plan, PlanAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(ProjectMember, ProjectMemberAdmin)
admin.site.register(ProjectTask, ProjectTaskAdmin)
