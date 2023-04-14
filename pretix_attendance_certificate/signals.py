from django.utils.translation import gettext_lazy as _
from django.urls import resolve, reverse
from django.dispatch import receiver
from pretix_attendance_certificate.views.emails import SendCertificateEmailView
from pretix.control.signals import (
    nav_event,
)
from pretix.plugins.sendmail.signals import sendmail_view_classes
from pretix.base.signals import logentry_display
from pretix.base.models import OrderPosition


@receiver(nav_event, dispatch_uid="certificate_of_attendance_nav")
def control_nav_import(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    p = request.user.has_event_permission(
        request.organizer, request.event, "can_change_settings", request
    ) or request.user.has_event_permission(
        request.organizer, request.event, "can_view_orders", request
    )
    if not p:
        return []
    return [
        {
            "label": _("Certificate of Attendance"),
            "url": reverse(
                "plugins:pretix_attendance_certificate:edit",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.event.organizer.slug,
                },
            ),
            "active": False,
            "icon": "id-card",
            "children": [
                {
                    "label": _("Editor"),
                    "url": reverse(
                        "plugins:pretix_attendance_certificate:edit",
                        kwargs={
                            "event": request.event.slug,
                            "organizer": request.event.organizer.slug,
                        },
                    ),
                    "active": url.namespace == "plugins:pretix_attendance_certificate"
                    and url.url_name == "edit",
                },
                {
                    "label": _("Send out certificates"),
                    "url": reverse(
                        "plugins:pretix_attendance_certificate:send",
                        kwargs={
                            "event": request.event.slug,
                            "organizer": request.event.organizer.slug,
                        },
                    ),
                    "active": url.namespace == "plugins:pretix_attendance_certificate"
                    and url.url_name == "send",
                },
            ],
        }
    ]


@receiver(
    sendmail_view_classes, dispatch_uid="pretix_attendance_certificate_sendmail_view"
)
def register_sendmail_view(sender, **kwargs):
    return [SendCertificateEmailView]


@receiver(
    signal=logentry_display,
    dispatch_uid="pretix_attendance_certificate_sendmail_view_logentry_display",
)
def logentry_display(sender, logentry, **kwargs):
    if logentry.action_type == "pretix_attendance_certificate.sent.attendee":
        order_position = OrderPosition.objects.get(id=logentry.parsed_data["position"])
        return _(
            "An email has been sent with the certificate of attendance "
            'to attendee "{attendee_name}"'
        ).format(attendee_name=order_position.attendee_name)

    if (
        logentry.action_type
        == "pretix.plugins.pretix_attendance_certificate.layout.changed"
    ):
        return _("The layout of the certificate of attendance has been changed.")

    if logentry.action_type == "pretix_attendance_certificate.sendmail.sent":
        return _("The certificate of attendance has been sent out to all attendees.")
