import datetime
from pretix.celery_app import app
from pretix.base.services.tasks import ProfiledEventTask
from pretix.base.models import Event, InvoiceAddress, OrderPosition, User, CachedFile
from i18nfield.strings import LazyI18nString
from pretix.base.services.mail import mail
from pretix.base.i18n import language
from pretix.helpers.format import format_map
from pretix.base.email import get_email_context
from pretix_attendance_certificate.render import render_certificate


@app.task(base=ProfiledEventTask, acks_late=True)
def send_certificate_of_attendance_mails(
    event: Event, user: int, subject: dict, message: dict, objects: list
):
    user = User.objects.get(pk=user) if user else None

    subject = LazyI18nString(subject)
    message = LazyI18nString(message)
    positions = OrderPosition.objects.filter(pk__in=objects, order__event=event)

    for position in positions:
        order = position.order

        try:
            invoice_address = order.invoice_address
        except InvoiceAddress.DoesNotExist:
            invoice_address = InvoiceAddress(order=order)

        with language(order.locale, event.settings.region):
            email_context = get_email_context(
                event=event,
                order=order,
                position=position,
                invoice_address=invoice_address,
            )
            rendered_certificate = render_certificate(position=position, event=event)
            cache_file = CachedFile.objects.create(
                filename="certificate_of_attendance.pdf",
                expires=datetime.datetime.now() + datetime.timedelta(days=7),
                file=rendered_certificate,
            )

            mail(
                position.attendee_email,
                subject,
                message,
                email_context,
                event,
                locale=order.locale,
                order=order,
                position=position,
                attach_tickets=False,
                attach_cached_files=[cache_file],
            )
            order.log_action(
                "pretix_attendance_certificate.sent.attendee",
                user=user,
                data={
                    "position": position.positionid,
                    "subject": format_map(
                        subject.localize(order.locale), email_context
                    ),
                    "message": format_map(
                        message.localize(order.locale), email_context
                    ),
                    "recipient": position.attendee_email,
                },
            )
