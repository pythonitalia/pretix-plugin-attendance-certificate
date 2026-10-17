from django.db import models
from django.db.models import Q
from django_scopes import scope
from django.utils.crypto import get_random_string
from i18nfield.fields import I18nCharField, I18nTextField
import string

from pretix.base.models import LoggedModel
from django.utils.translation import gettext_lazy as _


def bg_name(instance, filename: str) -> str:
    secret = get_random_string(
        length=16, allowed_chars=string.ascii_letters + string.digits
    )
    return "pub/{org}/{ev}/attendance_certificates/{id}-{secret}.pdf".format(
        org=instance.scope_organizer.slug,
        ev=instance.event.slug if instance.event_id else "_organizer",
        id=instance.pk,
        secret=secret,
    )


class AttendanceCertificateLayout(LoggedModel):
    event = models.ForeignKey(
        "pretixbase.Event",
        on_delete=models.CASCADE,
        related_name="attendance_certificate_layouts",
        null=True,
        blank=True,
    )
    organizer = models.ForeignKey(
        "pretixbase.Organizer",
        on_delete=models.CASCADE,
        related_name="attendance_certificate_layouts",
        null=True,
        blank=True,
    )
    active_events = models.ManyToManyField(
        "pretixbase.Event",
        through="LayoutActivation",
        through_fields=("layout", "event"),
        blank=True,
        related_name="active_organizer_certificate_layouts",
    )
    default = models.BooleanField(
        verbose_name=_("Default"),
        default=False,
    )
    name = models.CharField(max_length=190, verbose_name=_("Name"))
    layout = models.TextField(
        default=(
            '[{"type":"textarea","left":"13.09","bottom":"49.73","fontsize":"23.6","color":[0,0,0,1],'  # noqa
            '"fontfamily":"Open Sans","bold":true,"italic":false,"width":"121.83","content":"attendee_name",'  # noqa
            '"text":"Marco","align":"center"}]'  # noqa
        )
    )
    background = models.FileField(
        null=True, blank=True, upload_to=bg_name, max_length=255
    )
    mail_subject = I18nCharField(
        verbose_name=_("Email subject"),
        max_length=255,
        default="[{event}] Your certificate of attendance",
    )
    mail_text = I18nTextField(
        verbose_name=_("Email text"),
        default=(
            "Hello,\n\n"
            "please find your certificate of attendance for {event} attached to "
            "this email.\n\n"
            "Best regards"
        ),
    )

    def __str__(self):
        return self.name

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(event__isnull=False, organizer__isnull=True)
                    | Q(event__isnull=True, organizer__isnull=False)
                ),
                name="attendance_certificate_layout_event_xor_organizer",
            )
        ]

    @property
    def scope_organizer(self):
        return self.organizer or self.event.organizer

    @classmethod
    def visible_to(cls, event):
        """All layouts an event may view/manage: its own plus every
        organizer-wide one, regardless of whether it has been activated."""
        return cls.objects.filter(Q(event=event) | Q(organizer=event.organizer))


class LayoutActivation(models.Model):
    """Per-event settings of a template.

    For an organizer-wide template the existence of this row *is* the
    activation for the event. Event-owned templates are always available, so
    for them the row is optional and only carries the check-in list.
    """

    layout = models.ForeignKey(
        AttendanceCertificateLayout,
        on_delete=models.CASCADE,
        related_name="activations",
    )
    event = models.ForeignKey(
        "pretixbase.Event",
        on_delete=models.CASCADE,
        related_name="attendance_certificate_activations",
    )
    checkin_list = models.ForeignKey(
        "pretixbase.CheckinList",
        null=True,
        blank=True,
        # Deleting the list must never widen who is eligible: a pre_delete
        # hook (see signals.py) deactivates the template before this runs.
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("Check-in list"),
        help_text=_(
            "Only attendees checked in on this list are eligible for the "
            "template. Leave empty to make it available to everyone."
        ),
    )

    active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
        help_text=_(
            "Deactivated templates are not offered for this event. This is "
            "set automatically when the tied check-in list is deleted."
        ),
    )

    class Meta:
        unique_together = (("layout", "event"),)


def available_layouts(event):
    """Layouts actually usable for rendering a certificate for this event:
    its own layouts plus organizer-wide ones explicitly activated for it, minus
    any that were deactivated."""
    deactivated = LayoutActivation.objects.filter(event=event, active=False)
    return (
        AttendanceCertificateLayout.objects.filter(
            Q(event=event) | Q(organizer=event.organizer, active_events=event)
        )
        .exclude(pk__in=deactivated.values("layout_id"))
        .order_by("name", "pk")
        .distinct()
    )


class CertificateOption:
    """One template as seen from one attendee."""

    def __init__(self, layout, checkin_list, applicable):
        self.layout = layout
        self.checkin_list = checkin_list
        self.applicable = applicable

    @property
    def pk(self):
        return self.layout.pk


def certificate_options(position):
    """All templates available for the position's event, each flagged
    with whether the attendee is eligible (the template is tied to no check-in
    list, or the attendee has a successful check-in on that list)."""
    from pretix.base.models import Checkin

    event = position.order.event
    activations = {
        a.layout_id: a
        for a in LayoutActivation.objects.filter(event=event).select_related(
            "checkin_list"
        )
    }
    with scope(organizer=event.organizer):
        checked_in = set(
            Checkin.all.filter(position=position, successful=True).values_list(
                "list_id", flat=True
            )
        )
    options = []
    for layout in available_layouts(event):
        activation = activations.get(layout.pk)
        checkin_list = activation.checkin_list if activation else None
        options.append(
            CertificateOption(
                layout,
                checkin_list,
                checkin_list is None or checkin_list.pk in checked_in,
            )
        )
    return options
