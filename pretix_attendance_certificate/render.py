from pretix.base.i18n import language
from django.utils.translation import gettext as _
from io import BytesIO
from django.core.files import File
import json
from django.core.files.storage import default_storage
from django.contrib.staticfiles import finders
from pretix.base.pdf import Renderer
from pretix_attendance_certificate.models import (
    AttendanceCertificateLayout,
    available_layouts,
)
from reportlab.pdfgen import canvas
from reportlab.lib import pagesizes
from django.core.files.base import ContentFile
from pretix_attendance_certificate.signing import sign_pdf, signing_for


def _renderer(event, layout):
    if layout is None:
        return None
    if isinstance(layout.background, File) and layout.background.name:
        bgf = default_storage.open(layout.background.name, "rb")
    else:
        bgf = open(
            finders.find(
                "pretix_attendance_certificate/empty_attendance_certificate.pdf"
            ),
            "rb",
        )
    return Renderer(event, json.loads(layout.layout), bgf)


def resolve_single_layout(event):
    """Return the one layout available for event, or raise
    AttendanceCertificateLayout.DoesNotExist (none available) /
    MultipleObjectsReturned (more than one - caller must let the user pick)."""
    candidates = list(available_layouts(event)[:2])
    if not candidates:
        raise AttendanceCertificateLayout.DoesNotExist()
    if len(candidates) > 1:
        raise AttendanceCertificateLayout.MultipleObjectsReturned()
    return candidates[0]


def render_certificate(position, event, layout=None):
    Renderer._register_fonts()

    if layout is None:
        layout = resolve_single_layout(event)
    renderer = _renderer(event, layout)
    buffer = BytesIO()

    page = canvas.Canvas(buffer, pagesize=pagesizes.A4)

    with language(position.order.locale, position.order.event.settings.region):
        renderer.draw_page(page, position.order, position)

    page.save()
    buffer = renderer.render_background(buffer, _("Certificate of attendance"))
    content = buffer.read()

    # Never hand out an unsigned PDF while signing is switched on: if this
    # raises, the caller fails visibly instead of sending an unsigned file.
    signing = signing_for(event.organizer)
    if signing is not None:
        content = sign_pdf(content, signing)
    return ContentFile(content, name="certificate_of_attendance.pdf")
