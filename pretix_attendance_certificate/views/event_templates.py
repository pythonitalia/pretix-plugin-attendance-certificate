from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, TemplateView, UpdateView

from pretix.control.permissions import EventPermissionRequiredMixin
from pretix.helpers.compat import CompatDeleteView

from pretix_attendance_certificate.forms import OrganizerLayoutForm
from pretix_attendance_certificate.models import AttendanceCertificateLayout


class EventLayoutFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["locales"] = self.request.event.settings.get("locales")
        kwargs["event"] = self.request.event
        return kwargs


class EventLayoutListView(EventPermissionRequiredMixin, TemplateView):
    template_name = "pretix_attendance_certificate/event_layout_list.html"
    permission = ("can_change_event_settings", "can_view_orders")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event = self.request.event
        ctx["event_layouts"] = event.attendance_certificate_layouts.all()
        ctx["organizer_layouts"] = [
            {"layout": layout, "active": layout.active_events.filter(pk=event.pk).exists()}
            for layout in AttendanceCertificateLayout.objects.filter(
                organizer=event.organizer
            ).order_by("name")
        ]
        ctx["can_edit_organizer_layouts"] = self.request.user.has_organizer_permission(
            event.organizer, "can_change_organizer_settings", request=self.request
        )
        return ctx


def _require_change_permission(request):
    if not request.user.has_event_permission(
        request.organizer, request.event, "can_change_event_settings", request=request
    ):
        raise PermissionDenied(_("You do not have permission to view this content."))


class EventLayoutToggleView(EventPermissionRequiredMixin, TemplateView):
    permission = ("can_change_event_settings", "can_view_orders")

    def post(self, request, *args, **kwargs):
        _require_change_permission(request)
        layout = get_object_or_404(
            AttendanceCertificateLayout,
            organizer=request.event.organizer,
            pk=kwargs["layout"],
        )
        if layout.active_events.filter(pk=request.event.pk).exists():
            layout.active_events.remove(request.event)
            messages.success(
                request,
                _('The template "{name}" is no longer available for this event.').format(
                    name=layout.name
                ),
            )
        else:
            layout.active_events.add(request.event)
            messages.success(
                request,
                _('The template "{name}" is now available for this event.').format(
                    name=layout.name
                ),
            )
        return redirect(
            reverse(
                "plugins:pretix_attendance_certificate:layouts",
                kwargs={
                    "organizer": request.event.organizer.slug,
                    "event": request.event.slug,
                },
            )
        )


class EventLayoutCreateView(EventLayoutFormMixin, EventPermissionRequiredMixin, CreateView):
    model = AttendanceCertificateLayout
    template_name = "pretix_attendance_certificate/event_layout_edit.html"
    permission = "can_change_event_settings"
    form_class = OrganizerLayoutForm

    def get_success_url(self):
        return reverse(
            "plugins:pretix_attendance_certificate:layouts",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )

    def form_valid(self, form):
        form.instance.event = self.request.event
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


class EventLayoutUpdateView(EventLayoutFormMixin, EventPermissionRequiredMixin, UpdateView):
    model = AttendanceCertificateLayout
    template_name = "pretix_attendance_certificate/event_layout_edit.html"
    permission = "can_change_event_settings"
    form_class = OrganizerLayoutForm
    context_object_name = "layout"

    def get_object(self, queryset=None):
        return get_object_or_404(
            AttendanceCertificateLayout,
            event=self.request.event,
            pk=self.kwargs.get("layout"),
        )

    def get_success_url(self):
        return reverse(
            "plugins:pretix_attendance_certificate:layouts",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )

    def form_valid(self, form):
        messages.success(self.request, _("Your changes have been saved."))
        ret = super().form_valid(form)
        if form.has_changed():
            form.instance.log_action(
                "pretix.plugins.pretix_attendance_certificate.layout.changed",
                user=self.request.user,
                data={k: str(form.cleaned_data.get(k)) for k in form.changed_data},
            )
        return ret

    def form_invalid(self, form):
        messages.error(self.request, _("Your changes could not be saved."))
        return super().form_invalid(form)


class EventLayoutDeleteView(EventPermissionRequiredMixin, CompatDeleteView):
    model = AttendanceCertificateLayout
    template_name = "pretix_attendance_certificate/event_layout_delete.html"
    permission = "can_change_event_settings"
    context_object_name = "layout"

    def get_object(self, queryset=None):
        return get_object_or_404(
            AttendanceCertificateLayout,
            event=self.request.event,
            pk=self.kwargs.get("layout"),
        )

    def get_success_url(self):
        return reverse(
            "plugins:pretix_attendance_certificate:layouts",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
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
