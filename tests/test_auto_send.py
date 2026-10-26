from unittest.mock import Mock

import pytest
from django.urls import reverse

from pretix_attendance_certificate import checkin_handlers, tasks
from pretix_attendance_certificate.models import CertificateDelivery


@pytest.fixture
def apply_async(monkeypatch):
    apply_async = Mock()
    monkeypatch.setattr(
        tasks.send_automatic_certificate, "apply_async", apply_async
    )
    return apply_async


@pytest.mark.django_db
def test_auto_send_disabled_by_default(
    event, checkin, apply_async, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        checkin_handlers.on_checkin_created(sender=event, checkin=checkin)

    apply_async.assert_not_called()


@pytest.mark.django_db
def test_auto_send_enqueued_when_enabled(
    event, pos, checkin, apply_async, django_capture_on_commit_callbacks
):
    event.settings.attendance_certificate_auto_send = True

    with django_capture_on_commit_callbacks(execute=True):
        checkin_handlers.on_checkin_created(sender=event, checkin=checkin)

    apply_async.assert_called_once_with(
        kwargs={"event": event.pk, "position_id": pos.pk}
    )


def _event_url(event, name):
    return reverse(
        "plugins:pretix_attendance_certificate:" + name,
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )


@pytest.mark.django_db
def test_settings_page_enables_auto_send(settings_client, event):
    url = _event_url(event, "settings")
    assert settings_client.get(url).status_code == 200

    response = settings_client.post(
        url,
        {
            "attendance_certificate_auto_send": "on",
            "attendance_certificate_mail_subject_0": "Seu certificado",
            "attendance_certificate_mail_text_0": "Olá {event}",
        },
    )

    assert response.status_code == 302
    event.settings.flush()
    assert event.settings.attendance_certificate_auto_send is True
    assert str(event.settings.attendance_certificate_mail_subject) == (
        "Seu certificado"
    )


@pytest.mark.django_db
def test_delivery_history_lists_deliveries(logged_in_client, event, order, pos):
    CertificateDelivery.objects.create(
        position=pos,
        status=CertificateDelivery.STATUS_FAILED,
        recipient="attendee@dummy.test",
        error="mail server unavailable",
    )
    url = _event_url(event, "deliveries")

    content = logged_in_client.get(url).content.decode()
    assert "attendee@dummy.test" in content
    assert "mail server unavailable" in content

    content = logged_in_client.get(url + "?status=sent").content.decode()
    assert "attendee@dummy.test" not in content
