from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView

from pretix.control.permissions import OrganizerPermissionRequiredMixin
from pretix.control.views.organizer import OrganizerDetailViewMixin
from pretix.helpers.compat import CompatDeleteView

from pretix_attendance_certificate.forms import OrganizerLayoutForm
from pretix_attendance_certificate.models import AttendanceCertificateLayout


class OrganizerLayoutListView(OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, ListView):
    model = AttendanceCertificateLayout
    template_name = "pretix_attendance_certificate/organizer_layout_list.html"
    permission = "can_change_organizer_settings"
    context_object_name = "layouts"

    def get_queryset(self):
        return self.request.organizer.attendance_certificate_layouts.filter(
            event__isnull=True
        ).order_by("name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Editing a template's content always happens through the per-event
        # editor (it needs a concrete event to anchor permissions/preview
        # data on) - any event of this organizer that has the plugin enabled
        # works equally well as that anchor.
        ctx["anchor_event"] = (
            self.request.organizer.events.filter(
                plugins__icontains="pretix_attendance_certificate"
            )
            .order_by("date_from")
            .first()
        )
        ctx["layouts"] = [
            {"layout": layout, "active_events": list(layout.active_events.all())}
            for layout in ctx["layouts"]
        ]
        return ctx


class OrganizerLayoutCreateView(OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, CreateView):
    model = AttendanceCertificateLayout
    template_name = "pretix_attendance_certificate/organizer_layout_edit.html"
    permission = "can_change_organizer_settings"
    form_class = OrganizerLayoutForm

    def get_success_url(self):
        return reverse(
            "plugins:pretix_attendance_certificate:organizer.layouts",
            kwargs={"organizer": self.request.organizer.slug},
        )

    def form_valid(self, form):
        form.instance.organizer = self.request.organizer
        messages.success(self.request, _("The template has been created."))
        ret = super().form_valid(form)
        form.instance.log_action(
            "pretix.plugins.pretix_attendance_certificate.layout.changed",
            user=self.request.user,
            data={"name": form.instance.name},
        )
        return ret

    def form_invalid(self, form):
        messages.error(self.request, _("Your changes could not be saved."))
        return super().form_invalid(form)


class OrganizerLayoutDeleteView(OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, CompatDeleteView):
    model = AttendanceCertificateLayout
    template_name = "pretix_attendance_certificate/organizer_layout_delete.html"
    permission = "can_change_organizer_settings"
    context_object_name = "layout"

    def get_object(self, queryset=None):
        return get_object_or_404(
            AttendanceCertificateLayout,
            organizer=self.request.organizer,
            pk=self.kwargs.get("layout"),
        )

    def get_success_url(self):
        return reverse(
            "plugins:pretix_attendance_certificate:organizer.layouts",
            kwargs={"organizer": self.request.organizer.slug},
        )

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.log_action(
            "pretix.plugins.pretix_attendance_certificate.layout.deleted",
            user=self.request.user,
        )
        self.object.delete()
        messages.success(request, _("The template has been deleted."))
        return redirect(self.get_success_url())
