import pytest
from django.contrib.messages import get_messages
from django.core import mail as djmail
from django.urls import reverse
from django_scopes import scopes_disabled

from pretix.base.models import Team, User


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
    content = response.rendered_content
    assert _download_url(event, pos) in content
    assert "Email certificate" in content


@pytest.mark.django_db
def test_email_button_hidden_without_attendee_email(
    logged_in_client, event, order, pos, layout
):
    with scopes_disabled():
        pos.attendee_email = None
        pos.save()
    response = logged_in_client.get(_order_url(event, order))
    content = response.rendered_content
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
    assert djmail.outbox[0].subject == "Your certificate of attendance"
    assert any("attendee@dummy.test" in m for m in _messages(response))

    with scopes_disabled():
        assert (
            order.all_logentries()
            .filter(action_type="pretix_attendance_certificate.sent.attendee")
            .exists()
        )


@pytest.mark.django_db
def test_send_certificate_without_email(logged_in_client, event, order, pos, layout):
    with scopes_disabled():
        pos.attendee_email = None
        pos.save()
    djmail.outbox = []
    response = logged_in_client.post(_send_url(event, pos))
    assert response.status_code == 302
    assert len(djmail.outbox) == 0
    assert any("no email" in m.lower() for m in _messages(response))


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
