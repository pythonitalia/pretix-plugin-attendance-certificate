from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View

from pretix.base.models import OrderPosition
from pretix.control.permissions import EventPermissionRequiredMixin

from pretix_attendance_certificate.models import AttendanceCertificateLayout
from pretix_attendance_certificate.render import render_certificate
from pretix_attendance_certificate.tasks import send_certificate_of_attendance_mails

DEFAULT_SUBJECT = _("[{event}] Your certificate of attendance")
DEFAULT_MESSAGE = _(
    "Hello,\n\n"
    "please find your certificate of attendance for {event} attached to this "
    "email.\n\n"
    "Best regards"
)


def _get_position(request, pk) -> OrderPosition:
    return get_object_or_404(
        OrderPosition.objects.filter(order__event=request.event),
        pk=pk,
    )


def _order_url(request, order):
    return reverse(
        "control:event.order",
        kwargs={
            "event": request.event.slug,
            "organizer": request.event.organizer.slug,
            "code": order.code,
        },
    )


class DownloadCertificateView(EventPermissionRequiredMixin, View):
    permission = "can_view_orders"

    def get(self, request, *args, **kwargs):
        position = _get_position(request, kwargs["position"])
        try:
            certificate = render_certificate(position=position, event=request.event)
        except AttendanceCertificateLayout.DoesNotExist:
            messages.error(
                request,
                _(
                    "No certificate of attendance layout has been configured "
                    "for this event yet."
                ),
            )
            return redirect(_order_url(request, position.order))
        return FileResponse(
            certificate,
            as_attachment=True,
            filename="certificate-{code}-{pos}.pdf".format(
                code=position.order.code, pos=position.positionid
            ),
            content_type="application/pdf",
        )


class SendCertificateView(EventPermissionRequiredMixin, View):
    permission = "can_change_orders"

    def post(self, request, *args, **kwargs):
        position = _get_position(request, kwargs["position"])
        order = position.order

        # The task sends to position.attendee_email, so require it here too.
        recipient = position.attendee_email
        if not recipient:
            messages.error(
                request,
                _("This attendee has no email address to send the certificate to."),
            )
            return redirect(_order_url(request, order))

        send_certificate_of_attendance_mails.apply_async(
            kwargs={
                "event": request.event.pk,
                "user": request.user.pk,
                "subject": DEFAULT_SUBJECT,
                "message": DEFAULT_MESSAGE,
                "objects": [position.pk],
            }
        )
        messages.success(
            request,
            _("The certificate of attendance is being sent to {recipient}.").format(
                recipient=recipient
            ),
        )
        return redirect(_order_url(request, order))
