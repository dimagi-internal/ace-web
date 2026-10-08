import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.auth.models import PersonalToken
from apps.site_admin import api as site_admin_api
from apps.site_admin.models import StaffChange
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()
URL = "/api/site-admin/users"


def _user(email, staff=False, **kw):
    u = User.objects.create_user(email=email, **kw)
    if staff:
        User.objects.filter(pk=u.pk).update(is_staff=True)
        u.refresh_from_db()
    return u


@pytest.fixture
def staff(db):
    return _user("boss@example.com", staff=True, display_name="Boss")


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


def _patch(client, uid, is_staff, **kw):
    return client.patch(f"{URL}/{uid}", {"is_staff": is_staff},
                        content_type="application/json", **kw)


def test_anonymous_gets_401(client, db):
    assert client.get(URL).status_code == 401
    assert _patch(client, 1, True).status_code == 401


def test_non_staff_gets_404_on_list_and_patch(client, db):
    u = _user("plain@example.com")
    other = _user("o@example.com")
    client.force_login(u)
    r = client.get(URL)
    assert r.status_code == 404 and r["content-type"].startswith("application/problem+json")
    assert _patch(client, other.id, True).status_code == 404
    other.refresh_from_db()
    assert not other.is_staff


def test_non_staff_bearer_gets_404(client, db):
    u = _user("plain@example.com")
    raw, _ = PersonalToken.create_for_user(user=u, label="t")
    h = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
    assert client.get(URL, **h).status_code == 404
    assert _patch(client, u.id, True, **h).status_code == 404
    u.refresh_from_db()
    assert not u.is_staff


def test_staff_bearer_behaves_like_session(client, staff):
    target = _user("t@example.com")
    raw, _ = PersonalToken.create_for_user(user=staff, label="t")
    h = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
    assert client.get(URL, **h).status_code == 200
    assert _patch(client, target.id, True, **h).status_code == 200
    assert StaffChange.objects.get().changed_by_id == staff.id


def test_list_search_and_shape(staff_client, staff):
    ws = Workspace.objects.create(slug="spark", display_name="Spark", drive_root_folder_id="f",
                                  created_by=staff)
    ada = _user("ada@dimagi-ai.com", display_name="Ada")
    WorkspaceMembership.objects.create(workspace=ws, user=ada, role="editor")
    _user("zed@example.com", display_name="Zed")
    body = staff_client.get(URL).json()
    assert {u["email"] for u in body["users"]} == {
        "boss@example.com", "ada@dimagi-ai.com", "zed@example.com"}
    hit = staff_client.get(URL, {"q": "ADA"}).json()["users"]
    assert [u["email"] for u in hit] == ["ada@dimagi-ai.com"]
    assert hit[0]["workspaces"] == [
        {"workspace_slug": "spark", "workspace_name": "Spark", "role": "editor"}]
    assert [u["email"] for u in staff_client.get(URL, {"q": "zed"}).json()["users"]] == [
        "zed@example.com"]


def test_grant_writes_audit_and_shows_in_recent(staff_client):
    ada = _user("ada@dimagi-ai.com")
    r = _patch(staff_client, ada.id, True)
    assert r.status_code == 200 and r.json()["is_staff"] is True
    ada.refresh_from_db()
    assert ada.is_staff and not ada.is_superuser
    row = StaffChange.objects.get()
    assert (row.changed_by_email, row.target_email, row.old_is_staff, row.new_is_staff,
            row.source) == ("boss@example.com", "ada@dimagi-ai.com", False, True, "api")
    assert staff_client.get(URL).json()["recent_changes"][0]["target_email"] == "ada@dimagi-ai.com"


def test_noop_patch_writes_no_audit_row(staff_client):
    t = _user("t@example.com")
    assert _patch(staff_client, t.id, False).status_code == 200
    assert StaffChange.objects.count() == 0


def test_revoke_with_another_staff_remaining(staff_client):
    other = _user("other@example.com", staff=True)
    assert _patch(staff_client, other.id, False).status_code == 200
    other.refresh_from_db()
    assert not other.is_staff
    assert StaffChange.objects.get().new_is_staff is False


def test_cannot_remove_own_staff(staff_client, staff):
    _user("other@example.com", staff=True)
    r = _patch(staff_client, staff.id, False)
    assert r.status_code == 409 and "own site admin" in r.json()["detail"]
    staff.refresh_from_db()
    assert staff.is_staff and StaffChange.objects.count() == 0


def test_cannot_remove_last_staff(db, monkeypatch):
    # The self-guard fires first for a real caller, so the last-staff guard is
    # only reachable when the caller's staff row went away mid-request. Model
    # that: `actor` passes the staff check but only `target` is staff in the DB.
    actor = _user("a@example.com", staff=True)
    target = _user("t@example.com", staff=True)
    User.objects.filter(pk=actor.pk).update(is_staff=False)
    monkeypatch.setattr(site_admin_api, "_require_staff", lambda request: actor)
    c = Client()
    c.force_login(actor)
    r = _patch(c, target.id, False)
    assert r.status_code == 409 and "last site admin" in r.json()["detail"]
    target.refresh_from_db()
    assert target.is_staff and StaffChange.objects.count() == 0


def test_is_superuser_not_editable(staff_client):
    t = _user("t@example.com")
    r = staff_client.patch(f"{URL}/{t.id}", {"is_staff": True, "is_superuser": True},
                           content_type="application/json")
    assert r.status_code == 422
    t.refresh_from_db()
    assert not t.is_superuser and not t.is_staff


def test_unknown_user_404(staff_client):
    assert _patch(staff_client, 99999, True).status_code == 404


# --- bootstrap ---------------------------------------------------------------


@override_settings(ACE_SITE_ADMIN_EMAILS=["Jon@Example.com"])
def test_bootstrap_grants_listed_email_on_sign_in(client, db):
    jon = _user("jon@example.com")
    nope = _user("nope@example.com")
    client.force_login(nope)
    nope.refresh_from_db()
    assert not nope.is_staff
    client.force_login(jon)
    jon.refresh_from_db()
    assert jon.is_staff
    row = StaffChange.objects.get()
    assert (row.source, row.changed_by_id, row.target_email) == (
        "bootstrap", None, "jon@example.com")


@override_settings(ACE_SITE_ADMIN_EMAILS=[])
def test_bootstrap_default_empty_grants_nobody(client, db):
    u = _user("jon@example.com")
    client.force_login(u)
    u.refresh_from_db()
    assert not u.is_staff and StaffChange.objects.count() == 0
