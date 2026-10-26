from django.db import transaction
from django.dispatch import receiver

from pretix.base.models import Checkin
from pretix.base.signals import checkin_created

from pretix_attendance_certificate import email_defaults  # noqa: F401 (registers settings)


@receiver(
    checkin_created,
    dispatch_uid="attendance_certificate_auto_send",
)
def on_checkin_created(sender, checkin, **kwargs):
    """
    Detects a successful inbound check-in.

    The dispatch is scheduled only after the commit of the
    transaction that recorded the check-in.
    """

    if not sender.settings.attendance_certificate_auto_send:
        return

    if not checkin.successful:
        return

    if checkin.type != Checkin.TYPE_ENTRY:
        return

    event = sender
    position = checkin.position

    def enqueue_certificate():
        from pretix_attendance_certificate.tasks import (
            send_automatic_certificate,
        )

        send_automatic_certificate.apply_async(
            kwargs={
                "event": event.pk,
                "position_id": position.pk,
            }
        )

    transaction.on_commit(enqueue_certificate)
