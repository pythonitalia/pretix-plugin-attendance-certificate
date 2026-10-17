import re

import pytest
from django.test import RequestFactory
from django.urls import reverse
from django_scopes import scopes_disabled

from pretix.base.models import Team, User

from pretix_attendance_certificate.models import AttendanceCertificateLayout
from pretix_attendance_certificate.signals import control_nav_organizer_import


def _list_url(event):
    return reverse(
        "plugins:pretix_attendance_certificate:organizer.layouts",
        kwargs={"organizer": event.organizer.slug},
    )


def _add_url(event):
    return reverse(
        "plugins:pretix_attendance_certificate:organizer.layouts.add",
        kwargs={"organizer": event.organizer.slug},
    )


def _delete_url(event, layout):
    return reverse(
        "plugins:pretix_attendance_certificate:organizer.layouts.delete",
        kwargs={"organizer": event.organizer.slug, "layout": layout.pk},
    )


def _update_url(event, layout):
    return reverse(
        "plugins:pretix_attendance_certificate:organizer.layouts.update",
        kwargs={"organizer": event.organizer.slug, "layout": layout.pk},
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
def test_list_links_to_editor_via_anchor_event(organizer_client, event, organizer_layout):
    response = organizer_client.get(_list_url(event))
    assert _editor_url(event, organizer_layout) in response.rendered_content


@pytest.mark.django_db
def test_list_name_links_to_editor(organizer_client, event, organizer_layout):
    content = organizer_client.get(_list_url(event)).rendered_content
    pattern = rf'<strong>\s*<a href="{re.escape(_editor_url(event, organizer_layout))}">\s*{re.escape(organizer_layout.name)}'
    assert re.search(pattern, content)


@pytest.mark.django_db
def test_list_shows_which_events_use_a_template(organizer_client, event, organizer_layout):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
    response = organizer_client.get(_list_url(event))
    assert event.name in response.rendered_content
    assert "Not used by any event yet" not in response.rendered_content


@pytest.mark.django_db
def test_list_shows_not_used_hint_when_inactive(organizer_client, event, organizer_layout):
    response = organizer_client.get(_list_url(event))
    assert "Not used by any event yet" in response.rendered_content


@pytest.mark.django_db
def test_list_requires_organizer_permission(client, event):
    with scopes_disabled():
        user = User.objects.create_user("noperm@dummy.dummy", "noperm")
        team = Team.objects.create(organizer=event.organizer)
        team.members.add(user)
    client.force_login(user)
    response = client.get(_list_url(event))
    assert response.status_code != 200


@pytest.mark.django_db
def test_list_shows_organizer_layouts(organizer_client, event, organizer_layout):
    response = organizer_client.get(_list_url(event))
    assert response.status_code == 200
    assert organizer_layout.name in response.rendered_content


@pytest.mark.django_db
def test_list_does_not_show_event_owned_layouts(organizer_client, event, layout):
    response = organizer_client.get(_list_url(event))
    assert response.status_code == 200
    assert layout.name not in response.rendered_content


@pytest.mark.django_db
def test_create_organizer_layout(organizer_client, event):
    response = organizer_client.post(_add_url(event), {"name": "Kompetenznachweis"})
    assert response.status_code == 302

    with scopes_disabled():
        created = AttendanceCertificateLayout.objects.get(
            organizer=event.organizer, name="Kompetenznachweis"
        )
        assert created.event_id is None


@pytest.mark.django_db
def test_update_organizer_layout_name_and_mail_text(
    organizer_client, event, organizer_layout
):
    response = organizer_client.post(
        _update_url(event, organizer_layout),
        {
            "name": "Renamed template",
            "mail_subject_0": "New subject",
            "mail_text_0": "New body",
        },
    )
    assert response.status_code == 302
    with scopes_disabled():
        organizer_layout.refresh_from_db()
        assert organizer_layout.name == "Renamed template"
        assert str(organizer_layout.mail_subject) == "New subject"
        assert str(organizer_layout.mail_text) == "New body"


@pytest.mark.django_db
def test_update_organizer_layout_requires_permission(client, event, organizer_layout):
    with scopes_disabled():
        user = User.objects.create_user("noperm2@dummy.dummy", "noperm2")
        Team.objects.create(organizer=event.organizer).members.add(user)
    client.force_login(user)
    response = client.post(
        _update_url(event, organizer_layout), {"name": "Hijacked"}
    )
    assert response.status_code != 200
    with scopes_disabled():
        organizer_layout.refresh_from_db()
        assert organizer_layout.name != "Hijacked"


@pytest.mark.django_db
def test_list_links_name_to_update_view(organizer_client, event, organizer_layout):
    response = organizer_client.get(_list_url(event))
    assert _update_url(event, organizer_layout) in response.rendered_content


@pytest.mark.django_db
def test_delete_organizer_layout(organizer_client, event, organizer_layout):
    response = organizer_client.post(_delete_url(event, organizer_layout))
    assert response.status_code == 302
    with scopes_disabled():
        assert not AttendanceCertificateLayout.objects.filter(
            pk=organizer_layout.pk
        ).exists()


def _nav_request(event, user):
    from django.contrib.sessions.backends.db import SessionStore

    rf = RequestFactory()
    request = rf.get(_list_url(event))
    request.user = user
    request.session = SessionStore()
    return request


@pytest.mark.django_db
def test_nav_entry_hidden_without_permission(event):
    with scopes_disabled():
        user = User.objects.create_user("noperm@dummy.dummy", "noperm")
        Team.objects.create(organizer=event.organizer).members.add(user)
    entries = control_nav_organizer_import(
        None, request=_nav_request(event, user), organizer=event.organizer
    )
    assert entries == []


@pytest.mark.django_db
def test_nav_entry_hidden_without_active_event(event):
    with scopes_disabled():
        user = User.objects.create_user("orgadmin2@dummy.dummy", "orgadmin2")
        Team.objects.create(
            organizer=event.organizer, can_change_organizer_settings=True
        ).members.add(user)
        event.plugins = ""
        event.save()
    with scopes_disabled():
        entries = control_nav_organizer_import(
            None, request=_nav_request(event, user), organizer=event.organizer
        )
    assert entries == []


@pytest.mark.django_db
def test_nav_entry_shown_with_permission_and_active_event(organizer_client, event):
    with scopes_disabled():
        user = User.objects.get(email="orgadmin@dummy.dummy")
        entries = control_nav_organizer_import(
            None, request=_nav_request(event, user), organizer=event.organizer
        )
    assert len(entries) == 1
    assert entries[0]["label"] == "Certificate templates"
    assert entries[0]["icon"] == "id-card"
