import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


@pytest.fixture
def workspace_and_member(db):
    user = User.objects.create_user(email="a@example.com")
    workspace = Workspace.objects.create(
        slug="ws1",
        display_name="WS1",
        drive_root_folder_id="folder-1",
        created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    return workspace, user


@pytest.mark.django_db
def test_resolve_workspace_returns_workspace_for_member(workspace_and_member, rf):
    from apps.api.deps import resolve_workspace_for_member

    workspace, user = workspace_and_member
    request = rf.get("/api/w/ws1/")
    request.user = user
    result = resolve_workspace_for_member(request, "ws1")
    assert result.pk == workspace.pk


@pytest.mark.django_db
def test_resolve_workspace_404s_for_non_member(workspace_and_member, rf):
    from apps.api.deps import resolve_workspace_for_member
    from apps.api.errors import ProblemError

    workspace, _ = workspace_and_member
    outsider = User.objects.create_user(email="b@example.com")
    request = rf.get("/api/w/ws1/")
    request.user = outsider
    with pytest.raises(ProblemError) as exc_info:
        resolve_workspace_for_member(request, "ws1")
    assert exc_info.value.status_code == 404
