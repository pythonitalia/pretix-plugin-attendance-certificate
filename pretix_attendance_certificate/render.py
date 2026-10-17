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
from contextlib import nullcontext
from itertools import product
from i18nfield.strings import LazyI18nString
from reportlab.pdfbase import pdfmetrics
from pretix_attendance_certificate.markdown_text import (
    find_code_font,
    to_blocks,
    to_markup,
)

_HEADING_SIZES = {1: 1.6, 2: 1.4, 3: 1.2, 4: 1.1, 5: 1.0, 6: 1.0}


class _Entry:
    def __init__(self, paragraph, offset=0, bullet=None, bullet_offset=0, gap=0, rule=None):
        self.paragraph = paragraph
        self.offset = offset
        self.bullet = bullet
        self.bullet_offset = bullet_offset
        self.gap = gap
        self.rule = rule  # color of a horizontal rule (then there's no paragraph)
        self.height = 0


class _Stack:
    """Blocks below each other. Offers the part of reportlab's Paragraph API that
    pretix' text drawing uses, so that it can take the place of a Paragraph."""

    def __init__(self, entries):
        self.entries = entries
        self.height = 0

    def wrapOn(self, canvas, width, height):
        self.width = width
        total = 0
        for index, e in enumerate(self.entries):
            if e.paragraph is None:
                e.height = 1
            else:
                e.height = e.paragraph.wrapOn(canvas, width - e.offset, height)[1]
                if e.bullet is not None:
                    # right-aligned, with a gap to the text
                    e.bullet.wrapOn(canvas, (e.offset - e.bullet_offset) * 0.75, height)
            total += e.height + (e.gap if index else 0)
        self.height = total
        return width, total

    def getActualLineWidths0(self):
        return [
            w + e.offset
            for e in self.entries
            if e.paragraph is not None
            for w in e.paragraph.getActualLineWidths0()
        ]

    def drawOn(self, canvas, x, y):
        cursor = y + self.height
        for index, e in enumerate(self.entries):
            cursor -= e.height + (e.gap if index else 0)
            if e.paragraph is None:
                canvas.saveState()
                canvas.setStrokeColorRGB(*e.rule)
                canvas.setLineWidth(0.5)
                canvas.line(x + e.offset, cursor + 0.5, x + self.width, cursor + 0.5)
                canvas.restoreState()
                continue
            e.paragraph.drawOn(canvas, x + e.offset, cursor)
            if e.bullet is not None:
                # on the first line of the item, not the last
                e.bullet.drawOn(
                    canvas, x + e.bullet_offset, cursor + e.height - e.bullet.height
                )


class MarkdownRenderer(Renderer):
    """pretix' renderer, but the free text of text fields is Markdown (see
    markdown_text.py): paragraphs, headings, lists, links, **bold**, ..."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._register_font_families()
        self._code_font = find_code_font(self.event_fonts)

    def _register_font_families(self):
        # pretix registers "Open Sans", "Open Sans B", "Open Sans I", ... as
        # unrelated fonts; reportlab needs the families to map <b>/<i> onto them.
        names = set(pdfmetrics.getRegisteredFontNames())
        for family in self.event_fonts:

            def name(bold, italic):
                return family + (" B" if bold else "") + (" I" if italic else "")

            for bold, italic in product((False, True), repeat=2):
                if name(bold, italic) not in names:
                    continue
                variants = {
                    "normal": name(bold, italic),
                    "bold": name(True, italic),
                    "italic": name(bold, True),
                    "boldItalic": name(True, True),
                }
                pdfmetrics.registerFontFamily(
                    name(bold, italic),
                    **{k: v for k, v in variants.items() if v in names}
                )

    def _template_text(self, o):
        # Same language handling as in _get_text_content
        context = (
            language(o["locale"], self.event.settings.region)
            if o.get("locale")
            else nullcontext()
        )
        with context:
            if o["content"] == "other_i18n":
                return str(LazyI18nString(o.get("text_i18n", {})))
            return o.get("text", "")

    def _block_paragraph(self, op, order, o, text, legacy_lineheight, fontsize, **changes):
        block_element = dict(
            o, content="other", text=text, text_i18n={}, _markdown=True, **changes
        )
        return super()._text_paragraph(
            op, order, block_element, legacy_lineheight, fontsize
        )

    def _text_paragraph(self, op, order, o, legacy_lineheight=False, override_fontsize=None):
        if o.get("content") not in ("other", "other_i18n"):
            return super()._text_paragraph(
                op, order, o, legacy_lineheight, override_fontsize
            )
        blocks = to_blocks(self._template_text(o))
        fontsize = override_fontsize or float(o["fontsize"])
        step = fontsize * 1.6
        color = tuple(c / 255 for c in o["color"][:3])

        entries, first, previous = [], None, None
        for block in blocks:
            size = fontsize * (_HEADING_SIZES[block.level] if block.kind == "h" else 1)
            changes = {"bold": True} if block.kind == "h" else {}
            result = self._block_paragraph(
                op, order, o, block.text, legacy_lineheight, size, **changes
            )
            first = first or result
            paragraph = result[0]
            gap = 0
            if previous is not None and not (previous.in_list and block.in_list):
                gap = previous_leading
            previous, previous_leading = block, paragraph.style.leading
            if block.kind == "hr":
                entries.append(_Entry(None, block.indent * step, gap=gap, rule=color))
                continue
            bullet = None
            if block.marker:
                bullet = self._block_paragraph(
                    op, order, o, block.marker, legacy_lineheight, size, align="right"
                )[0]
            entries.append(
                _Entry(paragraph, block.indent * step, bullet, (block.indent - 1) * step, gap)
            )
        if first is None:
            return self._block_paragraph(op, order, o, "", legacy_lineheight, fontsize)
        if len(entries) == 1 and not entries[0].offset and entries[0].paragraph:
            return first
        return _Stack(entries), first[1], first[2]

    def _get_text_content(self, op, order, o, inner=False):
        text = super()._get_text_content(op, order, o, inner)
        if o.get("_markdown") and not inner:
            # Already escaped and tagged, so pretix must not escape it again.
            return to_markup(text, self._code_font)
        return text


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
    return MarkdownRenderer(event, json.loads(layout.layout), bgf)


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
