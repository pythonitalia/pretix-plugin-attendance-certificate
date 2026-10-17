import copy
from django.utils.translation import gettext_lazy as _
from django.urls import resolve, reverse
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.template.loader import get_template
from django.utils.safestring import mark_safe
from pretix_attendance_certificate.views.emails import SendCertificateEmailView
from pretix_attendance_certificate.views.presale import (
    SELF_SERVICE_SETTING,
    downloadable_options,
)
from pretix.control.signals import (
    nav_event,
    nav_organizer,
    order_position_buttons,
)
from pretix.plugins.sendmail.signals import sendmail_view_classes
from pretix.base.signals import event_copy_data, logentry_display
from pretix.multidomain.urlreverse import eventreverse
from pretix.presale.signals import order_info, position_info
from pretix.base.models import CheckinList, OrderPosition
from pretix_attendance_certificate.models import (
    AttendanceCertificateLayout,
    LayoutActivation,
    certificate_options,
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
            "label": _("Certificate of attendance"),
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
    pre_delete,
    sender=CheckinList,
    dispatch_uid="pretix_attendance_certificate_checkin_list_deleted",
)
def deactivate_templates_of_deleted_checkin_list(sender, instance, **kwargs):
    """Safety net: a template tied to a check-in list that gets deleted must
    not silently become available to everyone. Organizer-wide templates lose
    their activation for the event; event-owned ones are flagged inactive
    (they have no activation to remove) until someone re-activates them."""
    for activation in LayoutActivation.objects.filter(
        checkin_list=instance
    ).select_related("layout", "event"):
        layout, event = activation.layout, activation.event
        if layout.organizer_id:
            activation.delete()
        else:
            activation.active = False
            activation.save(update_fields=["active"])
        event.log_action(
            "pretix.plugins.pretix_attendance_certificate.layout.deactivated",
            data={"layout": layout.name, "checkin_list": instance.name},
        )


@receiver(
    event_copy_data, dispatch_uid="pretix_attendance_certificate_copy_data"
)
def copy_attendance_certificate_data(sender, other, **kwargs):
    """Event-owned templates aren't copied by pretix's generic event-copy
    machinery (only its own core models are) - this carries them over, along
    with which organizer-wide templates the source event had activated."""
    def copy_settings(old_layout, new_layout):
        old = LayoutActivation.objects.filter(layout=old_layout, event=other).first()
        if old is None:
            return
        # Check-in lists are copied by pretix itself; find the counterpart.
        checkin_list = (
            sender.checkin_lists.filter(name=old.checkin_list.name).first()
            if old.checkin_list
            else None
        )
        if old.checkin_list and checkin_list is None:
            # The counterpart list is missing in the new event: don't let the
            # template silently become available to everyone there.
            if new_layout.organizer_id:
                LayoutActivation.objects.filter(
                    layout=new_layout, event=sender
                ).delete()
                return
            old.active = False
        LayoutActivation.objects.update_or_create(
            layout=new_layout,
            event=sender,
            defaults={"checkin_list": checkin_list, "active": old.active},
        )

    for old_layout in other.attendance_certificate_layouts.all():
        new_layout = copy.copy(old_layout)
        new_layout.pk = None
        new_layout.event = sender
        new_layout.save()
        if old_layout.background and old_layout.background.name:
            new_layout.background.save("background.pdf", old_layout.background)
        copy_settings(old_layout, new_layout)

    if sender.organizer_id == other.organizer_id:
        activated = AttendanceCertificateLayout.objects.filter(
            organizer=other.organizer, active_events=other
        )
        for organizer_layout in activated:
            organizer_layout.active_events.add(sender)
            copy_settings(organizer_layout, organizer_layout)

    if other.settings.get(SELF_SERVICE_SETTING, as_type=bool, default=False):
        sender.settings.set(SELF_SERVICE_SETTING, True)


def _self_service_links(event, order, position, secret):
    return [
        {
            "name": option.layout.name,
            "url": eventreverse(
                event,
                "plugins:pretix_attendance_certificate:presale.download",
                kwargs={
                    "order": order.code,
                    "secret": secret,
                    "position": position.positionid,
                    "layout": option.pk,
                },
            ),
        }
        for option in downloadable_options(position)
    ]


def _render_self_service(request, rows):
    rows = [r for r in rows if r["links"]]
    if not rows:
        return ""
    return mark_safe(
        get_template("pretix_attendance_certificate/presale_certificates.html")
        .render({"rows": rows}, request=request)
        .strip()
    )


@receiver(order_info, dispatch_uid="pretix_attendance_certificate_order_info")
def presale_order_info(sender, order, request, **kwargs):
    return _render_self_service(
        request,
        [
            {
                "position": position,
                "links": _self_service_links(sender, order, position, order.secret),
            }
            for position in order.positions.select_related("item")
        ],
    )


@receiver(position_info, dispatch_uid="pretix_attendance_certificate_position_info")
def presale_position_info(sender, order, position, request, **kwargs):
    return _render_self_service(
        request,
        [
            {
                "position": position,
                "links": _self_service_links(
                    sender, order, position, position.web_secret
                ),
            }
        ],
    )


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
            "options": certificate_options(position),
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

    if (
        logentry.action_type
        == "pretix.plugins.pretix_attendance_certificate.layout.deactivated"
    ):
        return _(
            'The certificate template "{layout}" was deactivated because its '
            'check-in list "{checkin_list}" was deleted.'
        ).format(
            layout=logentry.parsed_data.get("layout"),
            checkin_list=logentry.parsed_data.get("checkin_list"),
        )

    if logentry.action_type == "pretix_attendance_certificate.sendmail.sent":
        return _("The certificate of attendance has been sent out to all attendees.")
