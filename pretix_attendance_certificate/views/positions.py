from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View

from pretix.base.models import OrderPosition
from pretix.control.permissions import EventPermissionRequiredMixin

from pretix_attendance_certificate.models import certificate_options
from pretix_attendance_certificate.render import render_certificate
from pretix_attendance_certificate.tasks import send_certificate_of_attendance_mails


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


def resolve_requested_layout(request, position):
    """Resolve which layout a download/send request for this position uses.

    Returns (layout, error_message), of which exactly one is not None: an
    explicit ?layout=<pk>/POST layout param is honored if the attendee is
    eligible for it, otherwise the attendee's only eligible template is used.
    Anything else is an error that the caller should show to the user - so a
    certificate for a template the attendee isn't eligible for can never be
    issued by accident.
    """
    options = certificate_options(position)
    layout_pk = request.GET.get("layout") or request.POST.get("layout")
    if layout_pk:
        try:
            option = next(o for o in options if o.pk == int(layout_pk))
        except (StopIteration, ValueError):
            return None, _("The requested template is not available for this event.")
        if not option.applicable:
            return None, _(
                'This attendee is not eligible for the template "{name}" '
                '(not checked in on list "{checkin_list}").'
            ).format(name=option.layout.name, checkin_list=option.checkin_list)
        return option.layout, None
    if not options:
        return None, _(
            "No certificate of attendance layout has been configured "
            "for this event yet."
        )
    eligible = [o for o in options if o.applicable]
    if not eligible:
        return None, _(
            "This attendee is not eligible for any certificate of attendance "
            "template."
        )
    if len(eligible) > 1:
        return None, _(
            "Multiple templates are available for this attendee - please pick "
            "one from the list."
        )
    return eligible[0].layout, None


class DownloadCertificateView(EventPermissionRequiredMixin, View):
    permission = "can_view_orders"

    def get(self, request, *args, **kwargs):
        position = _get_position(request, kwargs["position"])
        layout, error = resolve_requested_layout(request, position)
        if error:
            messages.error(request, error)
            return redirect(_order_url(request, position.order))
        certificate = render_certificate(
            position=position, event=request.event, layout=layout
        )
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

        # Fall back to the order's email if the position itself has none
        # (e.g. group bookings where only the buyer has an email address).
        recipient = position.attendee_email or order.email
        if not recipient:
            messages.error(
                request,
                _("This attendee has no email address to send the certificate to."),
            )
            return redirect(_order_url(request, order))

        layout, error = resolve_requested_layout(request, position)
        if error:
            messages.error(request, error)
            return redirect(_order_url(request, order))

        send_certificate_of_attendance_mails.apply_async(
            kwargs={
                "event": request.event.pk,
                "user": request.user.pk,
                "subject": layout.mail_subject.data,
                "message": layout.mail_text.data,
                "objects": [position.pk],
                "layout_id": layout.pk,
            }
        )
        messages.success(
            request,
            _("The certificate of attendance is being sent to {recipient}.").format(
                recipient=recipient
            ),
        )
        return redirect(_order_url(request, order))
