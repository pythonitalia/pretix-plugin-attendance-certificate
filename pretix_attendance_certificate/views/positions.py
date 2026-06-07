from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.views import View

from pretix.base.models import OrderPosition
from pretix.control.permissions import EventPermissionRequiredMixin

from pretix_attendance_certificate.render import render_certificate
from pretix_attendance_certificate.tasks import send_certificate_of_attendance_mails

DEFAULT_SUBJECT = _("Your certificate of attendance")
DEFAULT_MESSAGE = _(
    "Hello,\n\n"
    "please find your certificate of attendance for {event} attached to this "
    "email.\n\n"
    "Best regards"
)


def _localized(event, lazy_string) -> dict:
    """Resolve a lazy gettext string into an i18n dict for every event locale.

    Celery serializes task kwargs to JSON, so we have to materialize the
    translations here instead of passing a lazy object through.
    """
    data = {}
    for lng in event.settings.locales:
        with translation.override(lng):
            data[lng] = str(lazy_string)
    return data


def _get_position(request, pk) -> OrderPosition:
    return get_object_or_404(
        OrderPosition.objects.filter(order__event=request.event),
        pk=pk,
    )


class DownloadCertificateView(EventPermissionRequiredMixin, View):
    permission = "can_view_orders"

    def get(self, request, *args, **kwargs):
        position = _get_position(request, kwargs["position"])
        certificate = render_certificate(position=position, event=request.event)
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
            return redirect(self._order_url(order))

        send_certificate_of_attendance_mails.apply_async(
            kwargs={
                "event": request.event.pk,
                "user": request.user.pk,
                "subject": _localized(request.event, DEFAULT_SUBJECT),
                "message": _localized(request.event, DEFAULT_MESSAGE),
                "objects": [position.pk],
            }
        )
        messages.success(
            request,
            _("The certificate of attendance is being sent to {recipient}.").format(
                recipient=recipient
            ),
        )
        return redirect(self._order_url(order))

    def _order_url(self, order):
        return reverse(
            "control:event.order",
            kwargs={
                "event": self.request.event.slug,
                "organizer": self.request.event.organizer.slug,
                "code": order.code,
            },
        )
