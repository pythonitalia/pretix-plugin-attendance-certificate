import re

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


def _update_url(event, layout):
    return reverse(
        "plugins:pretix_attendance_certificate:layouts.update",
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


def _organizer_update_url(event, layout):
    return reverse(
        "plugins:pretix_attendance_certificate:organizer.layouts.update",
        kwargs={"organizer": event.organizer.slug, "layout": layout.pk},
    )


@pytest.mark.django_db
def test_list_shows_both_scopes(logged_in_client, event, layout, organizer_layout):
    response = logged_in_client.get(_list_url(event))
    assert response.status_code == 200
    assert layout.name in response.rendered_content
    assert organizer_layout.name in response.rendered_content
    assert "Inactive - click to activate" in response.rendered_content


@pytest.mark.django_db
def test_list_offers_design_and_mail_text_buttons_for_organizer_layouts(
    organizer_client, event, organizer_layout
):
    content = organizer_client.get(_list_url(event)).rendered_content
    assert _editor_url(event, organizer_layout) in content
    assert _organizer_update_url(event, organizer_layout) in content


@pytest.mark.django_db
def test_list_names_link_to_editor(organizer_client, event, layout, organizer_layout):
    content = organizer_client.get(_list_url(event)).rendered_content
    for lay in (layout, organizer_layout):
        pattern = rf'<a href="{re.escape(_editor_url(event, lay))}">\s*{re.escape(lay.name)}\s*</a>'
        assert re.search(pattern, content)


@pytest.mark.django_db
def test_list_hides_organizer_layout_buttons_without_organizer_permission(
    logged_in_client, event, organizer_layout
):
    content = logged_in_client.get(_list_url(event)).rendered_content
    assert _editor_url(event, organizer_layout) not in content
    assert _organizer_update_url(event, organizer_layout) not in content


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
def test_update_event_layout_name_and_mail_text(logged_in_client, event, layout):
    response = logged_in_client.post(
        _update_url(event, layout),
        {
            "name": "Renamed",
            "mail_subject_0": "New subject",
            "mail_text_0": "New body",
        },
    )
    assert response.status_code == 302
    with scopes_disabled():
        layout.refresh_from_db()
        assert layout.name == "Renamed"
        assert str(layout.mail_subject) == "New subject"
        assert str(layout.mail_text) == "New body"


@pytest.mark.django_db
def test_update_cannot_target_organizer_layout(logged_in_client, event, organizer_layout):
    response = logged_in_client.post(_update_url(event, organizer_layout), {"name": "x"})
    assert response.status_code == 404


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


# --- placeholder help text -------------------------------------------------


def _update_url(event, layout):
    return reverse(
        "plugins:pretix_attendance_certificate:layouts.update",
        kwargs={"organizer": event.organizer.slug, "event": event.slug, "layout": layout.pk},
    )


@pytest.mark.django_db
def test_event_template_help_matches_the_send_page_list(logged_in_client, event, layout):
    from pretix.base.email import get_available_placeholders

    event.settings.name_scheme = "given_family"
    with scopes_disabled():
        expected = sorted(
            get_available_placeholders(event, ["event", "order", "position_or_address"])
        )
    content = logged_in_client.get(_update_url(event, layout)).rendered_content
    assert "Available placeholders:" in content
    for key in expected:
        assert "{%s}" % key in content
    assert "{name_given_name}" in content


@pytest.mark.django_db
def test_event_template_help_includes_event_meta_data(logged_in_client, event, layout):
    from pretix.base.models.event import EventMetaProperty

    with scopes_disabled():
        EventMetaProperty.objects.create(organizer=event.organizer, name="Kurs", default="x")
    content = logged_in_client.get(_update_url(event, layout)).rendered_content
    assert "{meta_Kurs}" in content


@pytest.mark.django_db
def test_event_template_help_with_full_name_scheme(logged_in_client, event, layout):
    event.settings.name_scheme = "full"
    content = logged_in_client.get(_update_url(event, layout)).rendered_content
    # The list is generated for the event, so a part it doesn't have isn't offered.
    assert "{name}" in content
    assert "{name_given_name}" not in content


@pytest.mark.django_db
def test_organizer_template_form_gives_general_heads_up(organizer_client, event, organizer_layout):
    url = reverse(
        "plugins:pretix_attendance_certificate:organizer.layouts.update",
        kwargs={"organizer": event.organizer.slug, "layout": organizer_layout.pk},
    )
    content = organizer_client.get(url).rendered_content
    assert "{name}" in content
    assert "{name_given_name} (first name)" in content
    assert "only exist for events that collect the name in parts" in content
    assert "literal text" in content


# --- placeholder validation (event templates) ------------------------------


def _post_update(client, event, layout, **fields):
    data = {"name": layout.name, "mail_subject_0": "Subject", "mail_text_0": "Body"}
    data.update(fields)
    return client.post(_update_url(event, layout), data)


@pytest.mark.django_db
def test_event_template_accepts_valid_placeholders(logged_in_client, event, layout):
    event.settings.name_scheme = "given_family"
    response = _post_update(
        logged_in_client, event, layout,
        mail_subject_0="[{event}] for {name_given_name}",
        mail_text_0="Dear {name_for_salutation}, order {code}: {url}",
    )
    assert response.status_code == 302
    with scopes_disabled():
        layout.refresh_from_db()
        assert str(layout.mail_subject) == "[{event}] for {name_given_name}"


@pytest.mark.django_db
def test_event_template_rejects_unknown_placeholder(logged_in_client, event, layout):
    response = _post_update(logged_in_client, event, layout, mail_text_0="Hello {nmae}")
    assert response.status_code == 200
    assert "{nmae}" in response.rendered_content
    with scopes_disabled():
        layout.refresh_from_db()
        assert str(layout.mail_text) != "Hello {nmae}"


@pytest.mark.django_db
def test_event_template_rejects_name_part_the_event_does_not_have(
    logged_in_client, event, layout
):
    event.settings.name_scheme = "full"
    response = _post_update(
        logged_in_client, event, layout, mail_text_0="Hi {name_given_name}"
    )
    assert response.status_code == 200
    assert "{name_given_name}" in response.rendered_content


@pytest.mark.django_db
def test_event_template_rejects_unbalanced_braces(logged_in_client, event, layout):
    assert (
        _post_update(logged_in_client, event, layout, mail_text_0="Hi {name").status_code
        == 200
    )


@pytest.mark.django_db
def test_event_template_validates_every_language(logged_in_client, event, layout):
    event.settings.locales = ["en", "de"]
    ok = _post_update(logged_in_client, event, layout, mail_text_0="Hi {name}", mail_text_1="Hallo {name}")
    assert ok.status_code == 302
    bad = _post_update(logged_in_client, event, layout, mail_text_0="Hi {name}", mail_text_1="Hallo {nmae}")
    assert bad.status_code == 200


@pytest.mark.django_db
def test_organizer_template_is_not_validated_against_one_event(
    organizer_client, event, organizer_layout
):
    # An organizer-wide template has no single event to validate against.
    url = reverse(
        "plugins:pretix_attendance_certificate:organizer.layouts.update",
        kwargs={"organizer": event.organizer.slug, "layout": organizer_layout.pk},
    )
    response = organizer_client.post(
        url, {"name": "x", "mail_subject_0": "S", "mail_text_0": "Hi {name_given_name}"}
    )
    assert response.status_code == 302
