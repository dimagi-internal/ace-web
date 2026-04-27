from django.urls import path

from apps.workspaces import views

app_name = "workspaces"

urlpatterns = [
    path("", views.workspace_list, name="list"),
    path("drive-config/", views.drive_config, name="drive-config"),
    path("<slug:slug>/", views.workspace_detail, name="detail"),
]
