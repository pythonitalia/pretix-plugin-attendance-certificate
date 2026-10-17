import pytest
from django.contrib.messages import get_messages
from django.core import mail as djmail
from django.urls import reverse
from django_scopes import scopes_disabled

from pretix.base.models import Team, User

from pretix_attendance_certificate.models import AttendanceCertificateLayout


def _messages(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def _download_url(event, position):
    return reverse(
        "plugins:pretix_attendance_certificate:position.download",
        kwargs={
            "organizer": event.organizer.slug,
            "event": event.slug,
            "position": position.pk,
        },
    )


def _send_url(event, position):
    return reverse(
        "plugins:pretix_attendance_certificate:position.send",
        kwargs={
            "organizer": event.organizer.slug,
            "event": event.slug,
            "position": position.pk,
        },
    )


def _order_url(event, order):
    return "/control/event/{orga}/{event}/orders/{code}/".format(
        orga=event.organizer.slug, event=event.slug, code=order.code
    )


@pytest.mark.django_db
def test_position_buttons_rendered(logged_in_client, event, order, pos, layout):
    response = logged_in_client.get(_order_url(event, order))
    assert response.status_code == 200
    content = response.content.decode()
    assert _download_url(event, pos) in content
    assert "Email certificate" in content


@pytest.mark.django_db
def test_email_button_shown_with_order_email_fallback(
    logged_in_client, event, order, pos, layout
):
    # Group bookings often only have an order-level email, not a per-position
    # attendee email - the button must still show up in that case.
    with scopes_disabled():
        pos.attendee_email = None
        pos.save()
    response = logged_in_client.get(_order_url(event, order))
    content = response.content.decode()
    assert _download_url(event, pos) in content
    assert "Email certificate" in content


@pytest.mark.django_db
def test_email_button_hidden_without_any_email(
    logged_in_client, event, order, pos, layout
):
    with scopes_disabled():
        pos.attendee_email = None
        pos.save()
        order.email = None
        order.save()
    response = logged_in_client.get(_order_url(event, order))
    content = response.content.decode()
    # Download is always available, the email button is not.
    assert _download_url(event, pos) in content
    assert "Email certificate" not in content


@pytest.mark.django_db
def test_download_certificate(logged_in_client, event, order, pos, layout):
    response = logged_in_client.get(_download_url(event, pos))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert "attachment" in response["Content-Disposition"]
    body = b"".join(response.streaming_content)
    assert body.startswith(b"%PDF")


@pytest.mark.django_db
def test_send_certificate_email(logged_in_client, event, order, pos, layout):
    djmail.outbox = []
    response = logged_in_client.post(_send_url(event, pos))
    assert response.status_code == 302
    assert _order_url(event, order) in response.url

    assert len(djmail.outbox) == 1
    assert djmail.outbox[0].to == ["attendee@dummy.test"]
    # pretix >= 2025 prefixes the subject with the event name ("[Dummy] ...").
    assert djmail.outbox[0].subject.endswith("Your certificate of attendance")
    assert any("attendee@dummy.test" in m for m in _messages(response))

    with scopes_disabled():
        assert (
            order.all_logentries()
            .filter(action_type="pretix_attendance_certificate.sent.attendee")
            .exists()
        )


@pytest.mark.django_db
def test_send_certificate_uses_the_layouts_own_mail_text(
    logged_in_client, event, order, pos, layout
):
    with scopes_disabled():
        layout.mail_subject = "Custom subject for {event}"
        layout.mail_text = "Custom body text"
        layout.save()

    djmail.outbox = []
    response = logged_in_client.post(_send_url(event, pos))
    assert response.status_code == 302
    assert len(djmail.outbox) == 1
    assert djmail.outbox[0].subject == "Custom subject for Dummy"
    assert "Custom body text" in djmail.outbox[0].body


@pytest.mark.django_db
def test_send_certificate_falls_back_to_order_email(
    logged_in_client, event, order, pos, layout
):
    with scopes_disabled():
        pos.attendee_email = None
        pos.save()
    djmail.outbox = []
    response = logged_in_client.post(_send_url(event, pos))
    assert response.status_code == 302

    assert len(djmail.outbox) == 1
    assert djmail.outbox[0].to == ["dummy@dummy.test"]
    assert any("dummy@dummy.test" in m for m in _messages(response))

    with scopes_disabled():
        logentry = order.all_logentries().get(
            action_type="pretix_attendance_certificate.sent.attendee"
        )
        assert logentry.parsed_data["recipient"] == "dummy@dummy.test"


@pytest.mark.django_db
def test_send_certificate_with_multiple_layouts_requires_explicit_choice(
    logged_in_client, event, order, pos, layout, organizer_layout
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
    djmail.outbox = []
    response = logged_in_client.post(_send_url(event, pos))
    assert response.status_code == 302
    assert len(djmail.outbox) == 0
    assert any("multiple templates" in m.lower() for m in _messages(response))


@pytest.mark.django_db
def test_send_certificate_with_explicit_layout_param(
    logged_in_client, event, order, pos, layout, organizer_layout
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
    djmail.outbox = []
    response = logged_in_client.post(
        _send_url(event, pos), {"layout": organizer_layout.pk}
    )
    assert response.status_code == 302
    assert len(djmail.outbox) == 1


@pytest.mark.django_db
def test_position_buttons_show_one_send_form_per_layout(
    logged_in_client, event, order, pos, layout, organizer_layout
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
    response = logged_in_client.get(_order_url(event, order))
    content = response.content.decode()
    assert content.count('name="layout" value="{}"'.format(layout.pk)) == 1
    assert content.count('name="layout" value="{}"'.format(organizer_layout.pk)) == 1


@pytest.mark.django_db
def test_send_certificate_without_email(logged_in_client, event, order, pos, layout):
    with scopes_disabled():
        pos.attendee_email = None
        pos.save()
        order.email = None
        order.save()
    djmail.outbox = []
    response = logged_in_client.post(_send_url(event, pos))
    assert response.status_code == 302
    assert len(djmail.outbox) == 0
    assert any("no email" in m.lower() for m in _messages(response))


@pytest.mark.django_db
def test_download_without_any_layout(logged_in_client, event, order, pos):
    response = logged_in_client.get(_download_url(event, pos))
    assert response.status_code == 302
    assert any(
        "no certificate of attendance layout" in m.lower()
        for m in _messages(response)
    )


@pytest.mark.django_db
def test_download_with_multiple_layouts_requires_explicit_choice(
    logged_in_client, event, order, pos, layout, organizer_layout
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)

    # Both layout names show up as separate buttons on the order page.
    response = logged_in_client.get(_order_url(event, order))
    content = response.content.decode()
    assert layout.name in content
    assert organizer_layout.name in content

    # Downloading without picking one is an error, not a silent guess.
    response = logged_in_client.get(_download_url(event, pos))
    assert response.status_code == 302
    assert any(
        "multiple templates" in m.lower() for m in _messages(response)
    )


@pytest.mark.django_db
def test_download_with_explicit_layout_param(
    logged_in_client, event, order, pos, layout, organizer_layout
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)

    response = logged_in_client.get(_download_url(event, pos) + "?layout={}".format(
        organizer_layout.pk
    ))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_download_with_layout_param_not_available_for_event(
    logged_in_client, event, order, pos, layout
):
    with scopes_disabled():
        other_layout = AttendanceCertificateLayout.objects.create(
            organizer=event.organizer, name="Not activated"
        )
    response = logged_in_client.get(
        _download_url(event, pos) + "?layout={}".format(other_layout.pk)
    )
    assert response.status_code == 302
    assert any("not available" in m.lower() for m in _messages(response))


@pytest.mark.django_db
def test_download_requires_permission(client, event, order, pos, layout):
    with scopes_disabled():
        user = User.objects.create_user("noperm@dummy.dummy", "noperm")
        team = Team.objects.create(organizer=event.organizer, can_view_orders=False)
        team.members.add(user)
        team.limit_events.add(event)
    client.force_login(user)
    response = client.get(_download_url(event, pos))
    assert response.status_code != 200
