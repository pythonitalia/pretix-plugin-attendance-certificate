import copy
from django.utils.translation import gettext_lazy as _
from django.urls import resolve, reverse
from django.dispatch import receiver
from django.template.loader import get_template
from django.utils.safestring import mark_safe
from pretix_attendance_certificate.views.emails import SendCertificateEmailView
from pretix.control.signals import (
    nav_event,
    nav_organizer,
    order_position_buttons,
)
from pretix.plugins.sendmail.signals import sendmail_view_classes
from pretix.base.signals import event_copy_data, logentry_display
from pretix.base.models import OrderPosition
from pretix_attendance_certificate.models import (
    AttendanceCertificateLayout,
    available_layouts,
)


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
                "plugins:pretix_attendance_certificate:layouts",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.event.organizer.slug,
                },
            ),
            "active": False,
            "icon": "id-card",
            "children": [
                {
                    "label": _("Templates"),
                    "url": reverse(
                        "plugins:pretix_attendance_certificate:layouts",
                        kwargs={
                            "event": request.event.slug,
                            "organizer": request.event.organizer.slug,
                        },
                    ),
                    "active": url.namespace == "plugins:pretix_attendance_certificate"
                    and url.url_name in ("layouts", "edit"),
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


@receiver(nav_organizer, dispatch_uid="certificate_of_attendance_nav_organizer")
def control_nav_organizer_import(sender, request=None, organizer=None, **kwargs):
    if not request.user.has_organizer_permission(
        organizer, "can_change_organizer_settings", request=request
    ):
        return []
    if not organizer.events.filter(
        plugins__icontains="pretix_attendance_certificate"
    ).exists():
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": _("Certificate templates"),
            "url": reverse(
                "plugins:pretix_attendance_certificate:organizer.layouts",
                kwargs={"organizer": organizer.slug},
            ),
            "icon": "id-card",
            "active": url.namespace == "plugins:pretix_attendance_certificate"
            and url.url_name.startswith("organizer.layouts"),
        }
    ]


@receiver(
    event_copy_data, dispatch_uid="pretix_attendance_certificate_copy_data"
)
def copy_attendance_certificate_data(sender, other, **kwargs):
    """Event-owned templates aren't copied by pretix's generic event-copy
    machinery (only its own core models are) - this carries them over, along
    with which organizer-wide templates the source event had activated."""
    for old_layout in other.attendance_certificate_layouts.all():
        new_layout = copy.copy(old_layout)
        new_layout.pk = None
        new_layout.event = sender
        new_layout.save()
        if old_layout.background and old_layout.background.name:
            new_layout.background.save("background.pdf", old_layout.background)

    if sender.organizer_id == other.organizer_id:
        activated = AttendanceCertificateLayout.objects.filter(
            organizer=other.organizer, active_events=other
        )
        for organizer_layout in activated:
            organizer_layout.active_events.add(sender)


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
            "layouts": list(available_layouts(sender)),
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

    if (
        logentry.action_type
        == "pretix.plugins.pretix_attendance_certificate.layout.changed"
    ):
        return _("The layout of the certificate of attendance has been changed.")

    if (
        logentry.action_type
        == "pretix.plugins.pretix_attendance_certificate.layout.deleted"
    ):
        return _("A certificate of attendance template has been deleted.")

    if logentry.action_type == "pretix_attendance_certificate.sendmail.sent":
        return _("The certificate of attendance has been sent out to all attendees.")
