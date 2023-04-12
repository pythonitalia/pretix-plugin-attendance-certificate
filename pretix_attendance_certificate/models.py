from django.db import models
from django.utils.crypto import get_random_string
import string

from pretix.base.models import LoggedModel
from django.utils.translation import gettext_lazy as _


def bg_name(instance, filename: str) -> str:
    secret = get_random_string(
        length=16, allowed_chars=string.ascii_letters + string.digits
    )
    return "pub/{org}/{ev}/attendance_certificates/{id}-{secret}.pdf".format(
        org=instance.event.organizer.slug,
        ev=instance.event.slug,
        id=instance.pk,
        secret=secret,
    )


class AttendanceCertificateLayout(LoggedModel):
    event = models.ForeignKey(
        "pretixbase.Event",
        on_delete=models.CASCADE,
        related_name="attendance_certificate_layouts",
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
