from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from django_scopes import scope

from pretix_attendance_certificate import tasks
from pretix_attendance_certificate.models import CertificateDelivery


def _run_delivery(event, position, automatic):
    with scope(organizer=event.organizer):
        return tasks.send_certificate_of_attendance_mails.run(
            event=event,
            user=None,
            subject={"en": "Certificate"},
            message={"en": "Your certificate"},
            objects=[position.pk],
            automatic=automatic,
        )


def _mock_delivery_dependencies(monkeypatch, mail):
    monkeypatch.setattr(tasks, "has_valid_checkin", lambda position: True)
    monkeypatch.setattr(tasks, "get_email_context", lambda **kwargs: {})
    monkeypatch.setattr(tasks, "render_certificate", lambda **kwargs: Mock())
    monkeypatch.setattr(tasks, "language", lambda *args: nullcontext())
    monkeypatch.setattr(tasks, "mail", mail)
    monkeypatch.setattr(
        tasks.CachedFile.objects,
        "create",
        lambda **kwargs: Mock(),
    )
    monkeypatch.setattr(tasks, "format_map", lambda value, context: str(value))


@pytest.mark.django_db
def test_automatic_delivery_skips_second_attempt(event, pos, monkeypatch):
    mail = Mock()
    _mock_delivery_dependencies(monkeypatch, mail)

    _run_delivery(event, pos, automatic=True)
    _run_delivery(event, pos, automatic=True)

    assert mail.call_count == 1
    delivery = CertificateDelivery.objects.get(position=pos)
    assert delivery.status == CertificateDelivery.STATUS_SENT
    assert delivery.sent_at is not None


@pytest.mark.django_db
def test_manual_delivery_can_be_resent_after_automatic_delivery(
    event, pos, monkeypatch
):
    mail = Mock()
    _mock_delivery_dependencies(monkeypatch, mail)

    _run_delivery(event, pos, automatic=True)
    _run_delivery(event, pos, automatic=False)

    assert mail.call_count == 2
    assert CertificateDelivery.objects.get(position=pos).status == (
        CertificateDelivery.STATUS_SENT
    )


@pytest.mark.django_db
def test_delivery_failure_is_persisted(event, pos, monkeypatch):
    mail = Mock(side_effect=RuntimeError("mail server unavailable"))
    _mock_delivery_dependencies(monkeypatch, mail)

    _run_delivery(event, pos, automatic=True)

    delivery = CertificateDelivery.objects.get(position=pos)
    assert delivery.status == CertificateDelivery.STATUS_FAILED
    assert delivery.error == "mail server unavailable"
    assert delivery.recipient == "attendee@dummy.test"
    assert delivery.automatic is True


@pytest.mark.django_db
def test_failed_automatic_delivery_is_retried(event, pos, monkeypatch):
    mail = Mock(side_effect=[RuntimeError("mail server unavailable"), None])
    _mock_delivery_dependencies(monkeypatch, mail)

    _run_delivery(event, pos, automatic=True)
    _run_delivery(event, pos, automatic=True)

    assert mail.call_count == 2
    delivery = CertificateDelivery.objects.get(position=pos)
    assert delivery.status == CertificateDelivery.STATUS_SENT
    assert delivery.error == ""
