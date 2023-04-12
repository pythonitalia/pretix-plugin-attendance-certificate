from pretix.base.i18n import language
from django.utils.translation import gettext as _
from io import BytesIO
from django.core.files import File
import json
from django.core.files.storage import default_storage
from django.contrib.staticfiles import finders
from pretix.base.pdf import Renderer
from pretix_attendance_certificate.models import AttendanceCertificateLayout
from reportlab.pdfgen import canvas
from reportlab.lib import pagesizes
from django.core.files.base import ContentFile


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


def render_certificate(position, event):
    Renderer._register_fonts()

    layout = AttendanceCertificateLayout.objects.get(event=event)
    renderer = _renderer(event, layout)
    buffer = BytesIO()

    page = canvas.Canvas(buffer, pagesize=pagesizes.A4)

    with language(position.order.locale, position.order.event.settings.region):
        renderer.draw_page(page, position.order, position)

    page.save()
    buffer = renderer.render_background(buffer, _("Certificate of attendance"))
    return ContentFile(buffer.read(), name="certificate_of_attendance.pdf")
