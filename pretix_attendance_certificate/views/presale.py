from hmac import compare_digest

from django.http import FileResponse, Http404
from django.utils.timezone import now
from django.views import View
from django_scopes import scope

from pretix.base.models import Checkin, Order

from pretix_attendance_certificate.models import certificate_options
from pretix_attendance_certificate.render import render_certificate

SELF_SERVICE_SETTING = "attendance_certificate_self_service"


def self_service_enabled(event):
    return event.settings.get(SELF_SERVICE_SETTING, as_type=bool, default=False)


def event_is_over(position):
    """The attendee's event (or event date, for event series) has ended. Without
    an explicit end it counts as over once its start day is."""
    event = position.order.event
    date = position.subevent or event
    end = date.date_to
    if end is None:
        end = date.date_from.astimezone(event.timezone).replace(
            hour=23, minute=59, second=59
        )
    return end < now()


def was_present(position):
    """Someone has manually (or by scanning) checked the attendee in on any
    list - self-service never hands out a certificate on payment alone."""
    event = position.order.event
    with scope(organizer=event.organizer):
        return Checkin.all.filter(position=position, successful=True).exists()


def downloadable_options(position):
    """Templates the attendee may download themselves: the event must be over,
    the attendee must have been checked in, and tied templates additionally
    need their own check-in list."""
    order = position.order
    if (
        not self_service_enabled(order.event)
        or order.status != Order.STATUS_PAID
        or position.canceled
        or not position.item.admission
        or not event_is_over(position)
        or not was_present(position)
    ):
        return []
    return [o for o in certificate_options(position) if o.applicable]


class SelfServiceDownloadView(View):
    """Certificate download for attendees, authorized the same way as the
    order page: by knowing the order secret (or the ticket page's position
    secret)."""

    def get(self, request, *args, **kwargs):
        event = request.event
        order = event.orders.filter(code=kwargs["order"]).first()
        position = (
            order.positions.select_related("item")
            .filter(positionid=kwargs["position"])
            .first()
            if order
            else None
        )
        secret = kwargs["secret"].lower()
        if position is None or not (
            compare_digest(secret, order.secret.lower())
            or compare_digest(secret, position.web_secret.lower())
        ):
            raise Http404()
        option = next(
            (o for o in downloadable_options(position) if o.pk == int(kwargs["layout"])),
            None,
        )
        if option is None:
            raise Http404()
        return FileResponse(
            render_certificate(position=position, event=event, layout=option.layout),
            as_attachment=True,
            filename="certificate-{code}-{pos}.pdf".format(
                code=order.code, pos=position.positionid
            ),
            content_type="application/pdf",
        )
