# GUEST-VISIBILITY FORK — regression test
# This test is the upgrade safety net. Run after every rebase before deploy.
# If it fails, guest isolation is broken and the deploy MUST be blocked.

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    Issue,
    IssueComment,
    IssueLabel,
    Label,
    Project,
    ProjectMember,
    State,
    User,
    Workspace,
    WorkspaceMember,
)


@pytest.fixture
def guest_visibility_setup(db):
    """Set up workspace, project, users, labels, and issues for guest visibility tests."""
    # Users
    owner = User.objects.create(email="owner@test.so", first_name="Owner", last_name="User")
    owner.set_password("password")
    owner.save()

    guest = User.objects.create(email="guest@test.so", first_name="Guest", last_name="User")
    guest.set_password("password")
    guest.save()

    member = User.objects.create(email="member@test.so", first_name="Member", last_name="User")
    member.set_password("password")
    member.save()

    # Workspace
    workspace = Workspace.objects.create(name="Test WS", slug="test-ws", owner=owner)
    WorkspaceMember.objects.create(workspace=workspace, member=owner, role=20)
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
    WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)

    # Project (guest_view_all_features=False)
    project = Project.objects.create(
        name="Test Project",
        workspace=workspace,
        created_by=owner,
        updated_by=owner,
        identifier="TP",
        guest_view_all_features=False,
    )
    ProjectMember.objects.create(workspace=workspace, project=project, member=owner, role=20)
    ProjectMember.objects.create(workspace=workspace, project=project, member=guest, role=5)
    ProjectMember.objects.create(workspace=workspace, project=project, member=member, role=15)

    # State (required for issues)
    state = State.objects.create(
        name="Backlog",
        project=project,
        workspace=workspace,
        color="#000000",
        created_by=owner,
        updated_by=owner,
    )

    # Label
    guest_label = Label.objects.create(
        name="guest",
        workspace=workspace,
        project=project,
        created_by=owner,
        updated_by=owner,
    )

    # Issues
    tagged_issue = Issue.objects.create(
        name="Tagged Issue",
        project=project,
        workspace=workspace,
        state=state,
        created_by=owner,
        updated_by=owner,
    )
    IssueLabel.objects.create(
        issue=tagged_issue,
        label=guest_label,
        project=project,
        workspace=workspace,
        created_by=owner,
        updated_by=owner,
    )

    untagged_issue = Issue.objects.create(
        name="Untagged Issue",
        project=project,
        workspace=workspace,
        state=state,
        created_by=owner,
        updated_by=owner,
    )

    guest_created_issue = Issue.objects.create(
        name="Guest Created Issue",
        project=project,
        workspace=workspace,
        state=state,
        created_by=guest,
        updated_by=guest,
    )

    return {
        "workspace": workspace,
        "project": project,
        "owner": owner,
        "guest": guest,
        "member": member,
        "state": state,
        "guest_label": guest_label,
        "tagged_issue": tagged_issue,
        "untagged_issue": untagged_issue,
        "guest_created_issue": guest_created_issue,
    }


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class TestGuestVisibilityList:
    """Tests for issue list endpoints — guest should see own + guest-labelled issues."""

    def _list_url(self, slug, project_id):
        return f"/api/workspaces/{slug}/projects/{project_id}/issues/"

    @pytest.mark.django_db
    def test_guest_sees_tagged_issues(self, guest_visibility_setup):
        """Guest can see issues with the 'guest' label."""
        s = guest_visibility_setup
        client = _client_for(s["guest"])
        resp = client.get(self._list_url(s["workspace"].slug, s["project"].id))
        assert resp.status_code == status.HTTP_200_OK
        issue_ids = {str(i["id"]) for i in resp.data.get("results", resp.data) if isinstance(i, dict)}
        assert str(s["tagged_issue"].id) in issue_ids

    @pytest.mark.django_db
    def test_guest_sees_own_issues(self, guest_visibility_setup):
        """Guest can see issues they created (existing behavior preserved)."""
        s = guest_visibility_setup
        client = _client_for(s["guest"])
        resp = client.get(self._list_url(s["workspace"].slug, s["project"].id))
        assert resp.status_code == status.HTTP_200_OK
        issue_ids = {str(i["id"]) for i in resp.data.get("results", resp.data) if isinstance(i, dict)}
        assert str(s["guest_created_issue"].id) in issue_ids

    @pytest.mark.django_db
    def test_guest_cannot_see_untagged_issues(self, guest_visibility_setup):
        """Guest cannot see issues that are neither theirs nor guest-labelled."""
        s = guest_visibility_setup
        client = _client_for(s["guest"])
        resp = client.get(self._list_url(s["workspace"].slug, s["project"].id))
        assert resp.status_code == status.HTTP_200_OK
        issue_ids = {str(i["id"]) for i in resp.data.get("results", resp.data) if isinstance(i, dict)}
        assert str(s["untagged_issue"].id) not in issue_ids

    @pytest.mark.django_db
    def test_member_sees_all_issues(self, guest_visibility_setup):
        """Non-guest members see all issues regardless of label."""
        s = guest_visibility_setup
        client = _client_for(s["member"])
        resp = client.get(self._list_url(s["workspace"].slug, s["project"].id))
        assert resp.status_code == status.HTTP_200_OK
        issue_ids = {str(i["id"]) for i in resp.data.get("results", resp.data) if isinstance(i, dict)}
        assert str(s["tagged_issue"].id) in issue_ids
        assert str(s["untagged_issue"].id) in issue_ids
        assert str(s["guest_created_issue"].id) in issue_ids


class TestGuestVisibilityDetail:
    """Tests for issue detail endpoints — guest should get 403 on untagged issues."""

    def _detail_url(self, slug, project_id, issue_id):
        return f"/api/workspaces/{slug}/projects/{project_id}/issues/{issue_id}/"

    @pytest.mark.django_db
    def test_guest_can_retrieve_tagged_issue(self, guest_visibility_setup):
        """Guest can retrieve an issue with the 'guest' label."""
        s = guest_visibility_setup
        client = _client_for(s["guest"])
        resp = client.get(self._detail_url(s["workspace"].slug, s["project"].id, s["tagged_issue"].id))
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_guest_can_retrieve_own_issue(self, guest_visibility_setup):
        """Guest can retrieve an issue they created."""
        s = guest_visibility_setup
        client = _client_for(s["guest"])
        resp = client.get(self._detail_url(s["workspace"].slug, s["project"].id, s["guest_created_issue"].id))
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_guest_cannot_retrieve_untagged_issue(self, guest_visibility_setup):
        """Guest gets 403 for an issue that is neither theirs nor guest-labelled."""
        s = guest_visibility_setup
        client = _client_for(s["guest"])
        resp = client.get(self._detail_url(s["workspace"].slug, s["project"].id, s["untagged_issue"].id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN


class TestGuestVisibilityComments:
    """Tests for comment endpoints — guest can comment on own + guest-labelled issues."""

    def _comment_url(self, slug, project_id, issue_id):
        return f"/api/workspaces/{slug}/projects/{project_id}/issues/{issue_id}/comments/"

    @pytest.mark.django_db
    def test_guest_can_comment_on_tagged_issue(self, guest_visibility_setup):
        """Guest can comment on a guest-labelled issue."""
        s = guest_visibility_setup
        client = _client_for(s["guest"])
        resp = client.post(
            self._comment_url(s["workspace"].slug, s["project"].id, s["tagged_issue"].id),
            {"comment_html": "<p>test comment</p>"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

    @pytest.mark.django_db
    def test_guest_can_comment_on_own_issue(self, guest_visibility_setup):
        """Guest can comment on an issue they created."""
        s = guest_visibility_setup
        client = _client_for(s["guest"])
        resp = client.post(
            self._comment_url(s["workspace"].slug, s["project"].id, s["guest_created_issue"].id),
            {"comment_html": "<p>test comment</p>"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

    @pytest.mark.django_db
    def test_guest_cannot_comment_on_untagged_issue(self, guest_visibility_setup):
        """Guest cannot comment on an issue that is neither theirs nor guest-labelled."""
        s = guest_visibility_setup
        client = _client_for(s["guest"])
        resp = client.post(
            self._comment_url(s["workspace"].slug, s["project"].id, s["untagged_issue"].id),
            {"comment_html": "<p>test comment</p>"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestGuestViewAllFeatures:
    """When guest_view_all_features=True, guest sees everything (existing behavior unchanged)."""

    def _list_url(self, slug, project_id):
        return f"/api/workspaces/{slug}/projects/{project_id}/issues/"

    @pytest.mark.django_db
    def test_guest_sees_all_when_flag_true(self, guest_visibility_setup):
        """With guest_view_all_features=True, guest sees all issues."""
        s = guest_visibility_setup
        project = s["project"]
        project.guest_view_all_features = True
        project.save()

        client = _client_for(s["guest"])
        resp = client.get(self._list_url(s["workspace"].slug, project.id))
        assert resp.status_code == status.HTTP_200_OK
        issue_ids = {str(i["id"]) for i in resp.data.get("results", resp.data) if isinstance(i, dict)}
        assert str(s["tagged_issue"].id) in issue_ids
        assert str(s["untagged_issue"].id) in issue_ids
        assert str(s["guest_created_issue"].id) in issue_ids
