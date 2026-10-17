from django.core.exceptions import PermissionDenied
from django.core.files import File
from django.contrib.staticfiles import finders
from django.shortcuts import get_object_or_404
from reportlab.pdfgen import canvas
from django.core.files.storage import default_storage
from reportlab.lib import pagesizes
from io import BytesIO
from pretix.base.pdf import Renderer
from pretix_attendance_certificate.render import MarkdownRenderer
from pretix.base.models import CachedFile, OrderPosition
import json
from django.utils.translation import gettext_lazy as _
from django.utils.functional import cached_property
from pretix_attendance_certificate.models import AttendanceCertificateLayout
from pretix.control.permissions import EventPermissionRequiredMixin
from pretix.control.views.pdf import BaseEditorView
from django.templatetags.static import static


class EditorView(BaseEditorView):
    @classmethod
    def as_view(cls, **initkwargs):
        # Skip BaseEditorView's (= EventPermissionRequiredMixin's) hard-coded
        # event-only permission wrapping: whether an event- or organizer-level
        # permission is required depends on which layout is being targeted,
        # and that is only known once the `layout` kwarg (if any) is resolved
        # in dispatch() below.
        return super(EventPermissionRequiredMixin, cls).as_view(**initkwargs)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied()
        if self.layout.organizer_id:
            allowed = request.user.has_organizer_permission(
                request.organizer, "can_change_organizer_settings", request=request
            )
        else:
            allowed = request.user.has_event_permission(
                request.organizer,
                request.event,
                "can_change_event_settings",
                request=request,
            )
        if not allowed:
            raise PermissionDenied(_("You do not have permission to view this content."))
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def layout(self):
        layout_pk = self.kwargs.get("layout")
        if layout_pk:
            return get_object_or_404(
                AttendanceCertificateLayout.visible_to(self.request.event), pk=layout_pk
            )
        layout = self.request.event.attendance_certificate_layouts.first()
        if layout is None:
            layout = self.request.event.attendance_certificate_layouts.create(
                name=_("Default"),
                default=True,
            )
        return layout

    def get_default_background(self):
        return static("pretix_attendance_certificate/empty_attendance_certificate.pdf")

    def get_current_background(self):
        return (
            self.layout.background.url
            if self.layout and self.layout.background
            else self.get_default_background()
        )

    def save_background(self, f: CachedFile):
        if (
            self.layout.background
            and AttendanceCertificateLayout.objects.filter(
                background=self.layout.background
            ).count()
            == 1
        ):
            self.layout.background.delete()
        self.layout.background.save("background.pdf", f.file)

    def save_layout(self):
        update_fields = ["layout"]
        self.layout.layout = self.request.POST.get("data")
        if "name" in self.request.POST:
            self.layout.name = self.request.POST.get("name")
            update_fields.append("name")
        self.layout.save(update_fields=update_fields)
        self.layout.log_action(
            action="pretix.plugins.pretix_attendance_certificate.layout.changed",
            user=self.request.user,
            data={
                "layout": self.request.POST.get("data"),
                "name": self.request.POST.get("name"),
            },
        )

    def generate(
        self, op: OrderPosition, override_layout=None, override_background=None
    ):
        Renderer._register_fonts()

        buffer = BytesIO()
        if override_background:
            bgf = default_storage.open(override_background.name, "rb")
        elif isinstance(self.layout.background, File) and self.layout.background.name:
            bgf = default_storage.open(self.layout.background.name, "rb")
        else:
            bgf = open(
                finders.find(
                    "pretix_attendance_certificate/empty_attendance_certificate.pdf"
                ),
                "rb",
            )
        r = MarkdownRenderer(
            self.request.event,
            override_layout or self.get_current_layout(),
            bgf,
        )
        p = canvas.Canvas(buffer, pagesize=pagesizes.A4)
        r.draw_page(p, op.order, op)
        p.save()
        outbuffer = r.render_background(buffer, "Attendance Certificate")
        return "attendance-certificate.pdf", "application/pdf", outbuffer.read()

    def get_current_layout(self):
        return json.loads(self.layout.layout)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["name"] = self.layout.name
        return ctx

    @property
    def title(self):
        return _("Attendance Certificate layout")
