from django.db import models
from django.db.models import Q
from django.utils.crypto import get_random_string
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


def available_layouts(event):
    """Layouts actually usable for rendering a certificate for this event:
    its own layouts plus organizer-wide ones explicitly activated for it."""
    return AttendanceCertificateLayout.objects.filter(
        Q(event=event) | Q(organizer=event.organizer, active_events=event)
    ).distinct()
