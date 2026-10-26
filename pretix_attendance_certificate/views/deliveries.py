from django.views.generic import ListView

from pretix.control.permissions import EventPermissionRequiredMixin
from pretix.control.views import PaginationMixin

from pretix_attendance_certificate.models import CertificateDelivery


class DeliveryListView(EventPermissionRequiredMixin, PaginationMixin, ListView):
    model = CertificateDelivery
    permission = "can_view_orders"
    template_name = "pretix_attendance_certificate/deliveries.html"
    context_object_name = "deliveries"

    def get_queryset(self):
        qs = CertificateDelivery.objects.filter(
            position__order__event=self.request.event,
        ).select_related("position", "position__order")
        status = self.request.GET.get("status")
        if status in dict(CertificateDelivery.STATUS_CHOICES):
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = CertificateDelivery.STATUS_CHOICES
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["can_resend"] = self.request.user.has_event_permission(
            self.request.organizer,
            self.request.event,
            "can_change_orders",
            self.request,
        )
        return ctx
