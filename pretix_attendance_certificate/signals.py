from django.utils.translation import gettext_lazy as _
from django.urls import resolve, reverse
from django.dispatch import receiver
from django.template.loader import get_template
from django.utils.safestring import mark_safe
from pretix_attendance_certificate.views.emails import SendCertificateEmailView
from pretix.control.signals import (
    nav_event,
    nav_event_settings,
    order_position_buttons,
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
    nav = [
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
                {
                    "label": _("Delivery history"),
                    "url": reverse(
                        "plugins:pretix_attendance_certificate:deliveries",
                        kwargs={
                            "event": request.event.slug,
                            "organizer": request.event.organizer.slug,
                        },
                    ),
                    "active": url.namespace == "plugins:pretix_attendance_certificate"
                    and url.url_name == "deliveries",
                },
            ],
        }
    ]
    if request.user.has_event_permission(
        request.organizer, request.event, "can_change_event_settings", request
    ):
        nav[0]["children"].append(
            {
                "label": _("Settings"),
                "url": reverse(
                    "plugins:pretix_attendance_certificate:settings",
                    kwargs={
                        "event": request.event.slug,
                        "organizer": request.event.organizer.slug,
                    },
                ),
                "active": url.namespace == "plugins:pretix_attendance_certificate"
                and url.url_name == "settings",
            }
        )
    return nav


@receiver(nav_event_settings, dispatch_uid="certificate_of_attendance_nav_settings")
def control_nav_settings(sender, request=None, **kwargs):
    if not request.user.has_event_permission(
        request.organizer, request.event, "can_change_event_settings", request
    ):
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": _("Certificate of Attendance"),
            "url": reverse(
                "plugins:pretix_attendance_certificate:settings",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.event.organizer.slug,
                },
            ),
            "active": url.namespace == "plugins:pretix_attendance_certificate"
            and url.url_name == "settings",
        }
    ]


@receiver(
    sendmail_view_classes, dispatch_uid="pretix_attendance_certificate_sendmail_view"
)
def register_sendmail_view(sender, **kwargs):
    return [SendCertificateEmailView]


@receiver(
    order_position_buttons,
    dispatch_uid="pretix_attendance_certificate_order_position_buttons",
)
def control_order_position_buttons(sender, position, order, request, **kwargs):
    if not position.item.admission:
        return None

    template = get_template(
        "pretix_attendance_certificate/control_order_position_buttons.html"
    )
    return mark_safe(template.render(
        {
            "event": sender,
            "order": order,
            "position": position,
            "request": request,
        },
        request=request,
    ).strip())


@receiver(
    signal=logentry_display,
    dispatch_uid="pretix_attendance_certificate_sendmail_view_logentry_display",
)
def pretix_logentry_display(sender, logentry, **kwargs):
    if logentry.action_type == "pretix_attendance_certificate.sent.attendee":
        order_position = OrderPosition.objects.get(id=logentry.parsed_data["position"])
        return _(
            "An email has been sent with the certificate of attendance "
            'to attendee "{attendee_name}"'
        ).format(attendee_name=order_position.attendee_name)

    if logentry.action_type == "pretix_attendance_certificate.failed.attendee":
        return _(
            "The certificate of attendance could not be sent to {recipient}: {error}"
        ).format(
            recipient=logentry.parsed_data.get("recipient"),
            error=logentry.parsed_data.get("error"),
        )

    if logentry.action_type == "pretix_attendance_certificate.skipped.duplicate":
        return _(
            "The certificate of attendance was not sent automatically because it "
            "has already been sent."
        )

    if (
        logentry.action_type
        == "pretix.plugins.pretix_attendance_certificate.layout.changed"
    ):
        return _("The layout of the certificate of attendance has been changed.")

    if logentry.action_type == "pretix_attendance_certificate.sendmail.sent":
        return _("The certificate of attendance has been sent out to all attendees.")
