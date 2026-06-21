# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Guest-visibility fork — regression tests (markers live at the edit sites only).

Covers the swarmlabs fork behaviour (see issue #1): when a project has
``guest_view_all_features=False``, a guest-role member should see issues they
created **plus** any issue carrying the ``guest`` label (and may comment on
both). All existing behaviour is preserved.

Behaviour matrix:
    guest_view_all_features=True  -> guest sees everything            (unchanged)
    guest_view_all_features=False -> guest sees own issues            (unchanged)
    guest_view_all_features=False -> guest sees "guest"-labelled       (NEW)
    guest_view_all_features=False -> guest does NOT see untagged ones  (unchanged)
"""

from types import SimpleNamespace

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    Issue,
    IssueLabel,
    Label,
    Project,
    ProjectMember,
    User,
    Workspace,
    WorkspaceMember,
)

ROLE_ADMIN = 20
ROLE_GUEST = 5


@pytest.fixture(autouse=True)
def _no_celery(monkeypatch):
    """Neutralise background task dispatch so tests don't need a broker."""
    import plane.app.views.issue.base as base_views
    import plane.app.views.issue.comment as comment_views

    for module, attr in (
        (base_views, "recent_visited_task"),
        (comment_views, "issue_activity"),
        (comment_views, "model_activity"),
    ):
        monkeypatch.setattr(getattr(module, attr), "delay", lambda *a, **k: None)


def _build_world(guest_view_all_features):
    """Create a workspace/project with an owner, a guest, a 'guest' label, and
    three issues: one owned by the guest, one labelled 'guest' (owned by the
    owner), and one untagged (owned by the owner)."""
    # username is unique on the User model (defaults to ""), so set it explicitly
    owner = User.objects.create(email="owner@plane.so", username="gv-owner")
    workspace = Workspace.objects.create(name="GV WS", slug="gv-ws", owner=owner)
    WorkspaceMember.objects.create(workspace=workspace, member=owner, role=ROLE_ADMIN)

    project = Project.objects.create(
        name="GV Project",
        identifier="GVP",
        workspace=workspace,
        created_by=owner,
        guest_view_all_features=guest_view_all_features,
    )
    ProjectMember.objects.create(project=project, workspace=workspace, member=owner, role=ROLE_ADMIN)

    guest = User.objects.create(email="guest@plane.so", username="gv-guest")
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=ROLE_GUEST)
    ProjectMember.objects.create(project=project, workspace=workspace, member=guest, role=ROLE_GUEST)

    # workspace is auto-derived from project by WorkspaceBaseModel.save()
    guest_label = Label.objects.create(name="guest", project=project)

    own_issue = Issue.objects.create(name="Guest's own", project=project, workspace=workspace, created_by=guest)
    labelled_issue = Issue.objects.create(name="Labelled", project=project, workspace=workspace, created_by=owner)
    IssueLabel.objects.create(issue=labelled_issue, label=guest_label, project=project)
    untagged_issue = Issue.objects.create(name="Untagged", project=project, workspace=workspace, created_by=owner)

    return SimpleNamespace(
        owner=owner,
        guest=guest,
        workspace=workspace,
        project=project,
        own=own_issue,
        labelled=labelled_issue,
        untagged=untagged_issue,
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _issues_url(world):
    return f"/api/workspaces/{world.workspace.slug}/projects/{world.project.id}/issues/"


def _issue_url(world, issue):
    return f"/api/workspaces/{world.workspace.slug}/projects/{world.project.id}/issues/{issue.id}/"


def _comments_url(world, issue):
    return f"/api/workspaces/{world.workspace.slug}/projects/{world.project.id}/issues/{issue.id}/comments/"


def _result_ids(response):
    data = response.data
    results = data["results"] if isinstance(data, dict) and "results" in data else data
    return {str(row["id"]) for row in results}


@pytest.mark.unit
class TestGuestVisibility:
    # 1 — guest_view_all_features=True: guest sees ALL issues (unchanged)
    @pytest.mark.django_db
    def test_guest_sees_all_when_view_all_features_true(self):
        w = _build_world(guest_view_all_features=True)
        response = _client(w.guest).get(_issues_url(w))
        assert response.status_code == status.HTTP_200_OK
        ids = _result_ids(response)
        assert {str(w.own.id), str(w.labelled.id), str(w.untagged.id)} <= ids

    # 2 — guest_view_all_features=False: guest sees own issues, not others' untagged (unchanged)
    @pytest.mark.django_db
    def test_guest_sees_own_but_not_untagged_when_restricted(self):
        w = _build_world(guest_view_all_features=False)
        ids = _result_ids(_client(w.guest).get(_issues_url(w)))
        assert str(w.own.id) in ids
        assert str(w.untagged.id) not in ids

    # 3 — guest_view_all_features=False: guest ALSO sees "guest"-labelled issues (NEW)
    @pytest.mark.django_db
    def test_guest_sees_guest_labelled_issue_when_restricted(self):
        w = _build_world(guest_view_all_features=False)
        ids = _result_ids(_client(w.guest).get(_issues_url(w)))
        assert str(w.labelled.id) in ids

    # 4 — guest_view_all_features=False: retrieve is 403 for untagged, 200 for own + labelled
    @pytest.mark.django_db
    def test_guest_retrieve_permission_matrix(self):
        w = _build_world(guest_view_all_features=False)
        client = _client(w.guest)
        assert client.get(_issue_url(w, w.untagged)).status_code == status.HTTP_403_FORBIDDEN
        assert client.get(_issue_url(w, w.own)).status_code == status.HTTP_200_OK
        assert client.get(_issue_url(w, w.labelled)).status_code == status.HTTP_200_OK

    # 5 — guest can comment on their own issue (unchanged)
    @pytest.mark.django_db
    def test_guest_can_comment_on_own_issue(self):
        w = _build_world(guest_view_all_features=False)
        response = _client(w.guest).post(
            _comments_url(w, w.own), {"comment_html": "<p>mine</p>"}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED

    # 6 — guest can comment on a "guest"-labelled issue (NEW)
    @pytest.mark.django_db
    def test_guest_can_comment_on_labelled_issue(self):
        w = _build_world(guest_view_all_features=False)
        response = _client(w.guest).post(
            _comments_url(w, w.labelled), {"comment_html": "<p>shared</p>"}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED

    # 7 — guest cannot comment on an untagged issue owned by someone else
    @pytest.mark.django_db
    def test_guest_cannot_comment_on_untagged_issue(self):
        w = _build_world(guest_view_all_features=False)
        response = _client(w.guest).post(
            _comments_url(w, w.untagged), {"comment_html": "<p>nope</p>"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # 8 — a non-guest member sees every issue regardless of label
    @pytest.mark.django_db
    def test_non_guest_sees_all_issues(self):
        w = _build_world(guest_view_all_features=False)
        ids = _result_ids(_client(w.owner).get(_issues_url(w)))
        assert {str(w.own.id), str(w.labelled.id), str(w.untagged.id)} <= ids
