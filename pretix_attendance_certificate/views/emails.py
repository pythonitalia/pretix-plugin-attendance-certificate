from django.urls import reverse
from django.template.loader import get_template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.translation import gettext_lazy as _, ngettext

from pretix.plugins.sendmail.views import BaseSenderView
from pretix.plugins.sendmail.forms import BaseMailForm
from pretix.base.models import OrderPosition, Order

from pretix_attendance_certificate.tasks import send_certificate_of_attendance_mails


class CertificateEmailForm(BaseMailForm):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)


class SendCertificateEmailView(BaseSenderView):
    form_class = CertificateEmailForm
    form_fragment_name = (
        "pretix_attendance_certificate/send_form_fragment_attendance_certificate.html"
    )
    context_parameters = ["event", "order", "position_or_address"]
    task = send_certificate_of_attendance_mails

    ACTION_TYPE = "pretix_attendance_certificate.sendmail.sent"
    TITLE = _("Attendance Certificate")
    DESCRIPTION = _("Send out the attendance certificates to attendees.")

    @classmethod
    def get_url(cls, event):
        return reverse(
            "plugins:pretix_attendance_certificate:send",
            kwargs={
                "event": event.slug,
                "organizer": event.organizer.slug,
            },
        )

    def get_object_queryset(self, form):
        event = self.request.event
        return OrderPosition.objects.filter(
            canceled=False,
            item__admission=True,
            order__event=event,
            order__status__in=[Order.STATUS_PAID],
        ).distinct()

    def describe_match_size(self, cnt):
        return ngettext(
            "%(number)s matching ticket",
            "%(number)s matching tickets",
            cnt or 0,
        ) % {
            "number": intcomma(cnt or 0),
        }

    def get_task_kwargs(self, form, objects):
        kwargs = super().get_task_kwargs(form, objects)
        return kwargs

    @classmethod
    def show_history_meta_data(cls, logentry, _cache_store):
        tpl = get_template(
            "pretix_attendance_certificate/history_fragment_attendance_certificate.html"
        )
        return tpl.render(
            {
                "log": logentry,
            }
        )
