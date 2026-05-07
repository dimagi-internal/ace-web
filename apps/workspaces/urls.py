from django.urls import path

from apps.workspaces import views

app_name = "workspaces"

urlpatterns = [
    path("", views.workspace_collection, name="collection"),
    path("drive-config/", views.drive_config, name="drive-config"),
    path("<slug:slug>/", views.workspace_detail, name="detail"),
    path(
        "<slug:slug>/verify-drive-access/",
        views.verify_drive_access,
        name="verify-drive-access",
    ),
    path("<slug:slug>/members/", views.member_collection, name="members"),
    path(
        "<slug:slug>/members/<int:user_id>/",
        views.member_detail,
        name="member-detail",
    ),
    path("<slug:slug>/leave/", views.leave_workspace, name="leave"),
    path("<slug:slug>/activity/", views.workspace_activity, name="activity"),
    path(
        "<slug:slug>/pending-reviews/",
        views.pending_reviews,
        name="pending-reviews",
    ),
]
