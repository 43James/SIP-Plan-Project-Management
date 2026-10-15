from django.urls import path
from .views import (
    DashboardView, PlanListView, PlanCreateView, PlanUpdateView, PlanDetailView, ProjectCreateView,
    ProjectListView, MyProjectListView, ProjectDetailView, ProjectUpdateView, ProjectDeleteView, ProjectMemberCreateView, ProjectMemberDeleteView,
    ProjectTaskCreateView, ProjectTaskUpdateView, ProjectTaskDeleteView
)
from . import views

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('projects/', ProjectListView.as_view(), name='project_list'),
    path('projects/my/', MyProjectListView.as_view(), name='my_project_list'),
    path('plans/', PlanListView.as_view(), name='plan_list'),
    path('plans/create/', PlanCreateView.as_view(), name='plan_create'),
    path('plans/<int:pk>/', PlanDetailView.as_view(), name='plan_detail'),
    path('plans/<int:pk>/edit/', PlanUpdateView.as_view(), name='plan_edit'),
    path('project/create/', ProjectCreateView.as_view(), name='project_create'),
    path('project/<int:pk>/', ProjectDetailView.as_view(), name='project_detail'),
    path('project/<int:pk>/edit/', ProjectUpdateView.as_view(), name='project_edit'),
    path('project/<int:pk>/delete/', ProjectDeleteView.as_view(), name='project_delete'),
    path('project/<int:pk>/member/add/', ProjectMemberCreateView.as_view(), name='project_member_add'),
    path('member/<int:pk>/delete/', ProjectMemberDeleteView.as_view(), name='project_member_delete'),
    path('project/<int:pk>/task/add/', ProjectTaskCreateView.as_view(), name='project_task_add'),
    path('task/<int:pk>/edit/', ProjectTaskUpdateView.as_view(), name='project_task_edit'),
    path('task/<int:pk>/delete/', ProjectTaskDeleteView.as_view(), name='project_task_delete'),
    # Task attachments
    path('task/<int:pk>/attach/', views.task_attachment_upload, name='task_attachment_upload'),
    path('attachment/<int:pk>/delete/', views.task_attachment_delete, name='task_attachment_delete'),
    # Task comments
    path('task/<int:pk>/comment/', views.task_comment_create, name='task_comment_create'),
    path('comment/<int:pk>/delete/', views.task_comment_delete, name='task_comment_delete'),
    # Task followers
    path('task/<int:pk>/follow/', views.task_follower_toggle, name='task_follower_toggle'),
    # Task Board & Groups
    path('project/<int:pk>/board/', views.ProjectTaskBoardView.as_view(), name='project_task_board'),
    path('project/<int:project_pk>/group/add/', views.task_group_create, name='task_group_create'),
    path('group/<int:pk>/delete/', views.task_group_delete, name='task_group_delete'),
    path('group/<int:pk>/edit/', views.task_group_edit, name='task_group_edit'),
    # Task Tags APIs
    path('project/<int:project_id>/tag/create/', views.task_tag_create_api, name='task_tag_create_api'),
    path('tag/<int:tag_id>/update/', views.task_tag_update_api, name='task_tag_update_api'),
    path('tag/<int:tag_id>/delete/', views.task_tag_delete_api, name='task_tag_delete_api'),
]
