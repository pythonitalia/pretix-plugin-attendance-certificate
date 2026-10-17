import pytest
from django.urls import reverse
from django_scopes import scopes_disabled

from pretix.base.models import Team, User

from pretix_attendance_certificate.models import AttendanceCertificateLayout


def _list_url(event):
    return reverse(
        "plugins:pretix_attendance_certificate:layouts",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )


def _toggle_url(event, layout):
    return reverse(
        "plugins:pretix_attendance_certificate:layouts.toggle",
        kwargs={
            "organizer": event.organizer.slug,
            "event": event.slug,
            "layout": layout.pk,
        },
    )


def _add_url(event):
    return reverse(
        "plugins:pretix_attendance_certificate:layouts.add",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )


def _delete_url(event, layout):
    return reverse(
        "plugins:pretix_attendance_certificate:layouts.delete",
        kwargs={
            "organizer": event.organizer.slug,
            "event": event.slug,
            "layout": layout.pk,
        },
    )


def _editor_url(event, layout):
    return reverse(
        "plugins:pretix_attendance_certificate:edit",
        kwargs={
            "organizer": event.organizer.slug,
            "event": event.slug,
            "layout": layout.pk,
        },
    )


@pytest.mark.django_db
def test_list_shows_both_scopes(logged_in_client, event, layout, organizer_layout):
    response = logged_in_client.get(_list_url(event))
    assert response.status_code == 200
    assert layout.name in response.rendered_content
    assert organizer_layout.name in response.rendered_content
    assert "Inactive - click to activate" in response.rendered_content


@pytest.mark.django_db
def test_toggle_activates_and_deactivates(logged_in_client, event, organizer_layout):
    response = logged_in_client.post(_toggle_url(event, organizer_layout))
    assert response.status_code == 302
    with scopes_disabled():
        assert organizer_layout.active_events.filter(pk=event.pk).exists()

    response = logged_in_client.post(_toggle_url(event, organizer_layout))
    assert response.status_code == 302
    with scopes_disabled():
        assert not organizer_layout.active_events.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_toggle_requires_change_permission(client, event, organizer_layout):
    with scopes_disabled():
        user = User.objects.create_user("vieweronly@dummy.dummy", "vieweronly")
        team = Team.objects.create(organizer=event.organizer, can_view_orders=True)
        team.members.add(user)
        team.limit_events.add(event)
    client.force_login(user)
    response = client.post(_toggle_url(event, organizer_layout))
    assert response.status_code != 302
    with scopes_disabled():
        assert not organizer_layout.active_events.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_create_event_owned_layout(logged_in_client, event):
    response = logged_in_client.post(_add_url(event), {"name": "Kompetenznachweis"})
    assert response.status_code == 302
    with scopes_disabled():
        created = AttendanceCertificateLayout.objects.get(
            event=event, name="Kompetenznachweis"
        )
        assert created.organizer_id is None


@pytest.mark.django_db
def test_delete_event_owned_layout(logged_in_client, event, layout):
    response = logged_in_client.post(_delete_url(event, layout))
    assert response.status_code == 302
    with scopes_disabled():
        assert not AttendanceCertificateLayout.objects.filter(pk=layout.pk).exists()


@pytest.mark.django_db
def test_delete_cannot_target_organizer_layout(logged_in_client, event, organizer_layout):
    response = logged_in_client.post(_delete_url(event, organizer_layout))
    assert response.status_code == 404
    with scopes_disabled():
        assert AttendanceCertificateLayout.objects.filter(pk=organizer_layout.pk).exists()


@pytest.mark.django_db
def test_editing_event_layout_needs_only_event_permission(logged_in_client, event, layout):
    response = logged_in_client.get(_editor_url(event, layout))
    assert response.status_code == 200


@pytest.mark.django_db
def test_editing_organizer_layout_requires_organizer_permission(
    logged_in_client, event, organizer_layout
):
    # logged_in_client only has event-scoped permission, no organizer-wide one.
    response = logged_in_client.get(_editor_url(event, organizer_layout))
    assert response.status_code != 200


@pytest.mark.django_db
def test_editing_organizer_layout_with_organizer_permission(
    organizer_client, event, organizer_layout
):
    response = organizer_client.get(_editor_url(event, organizer_layout))
    assert response.status_code == 200
