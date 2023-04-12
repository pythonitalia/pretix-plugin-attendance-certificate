from django.utils.translation import gettext_lazy as _
from django.urls import resolve, reverse
from django.dispatch import receiver
from pretix_attendance_certificate.views.emails import SendCertificateEmailView
from pretix.control.signals import (
    nav_event,
)
from pretix.plugins.sendmail.signals import sendmail_view_classes


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
            "active": url.namespace == "plugins:pretix_attendance_certificate",
            "icon": "id-card",
            "children": [
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
                }
            ],
        }
    ]


@receiver(
    sendmail_view_classes, dispatch_uid="pretix_attendance_certificate_sendmail_view"
)
def register_sendmail_view(sender, **kwargs):
    return [SendCertificateEmailView]
