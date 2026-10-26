from django import forms
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from i18nfield.forms import I18nFormField, I18nTextarea, I18nTextInput

from pretix.base.forms import SettingsForm
from pretix.base.models import Event
from pretix.control.views.event import EventSettingsFormView, EventSettingsViewMixin


class AttendanceCertificateSettingsForm(SettingsForm):
    attendance_certificate_auto_send = forms.BooleanField(
        label=_("Send certificates automatically after check-in"),
        help_text=_(
            "Each attendee receives the certificate of attendance by email "
            "after their first successful entry check-in. Further check-ins do "
            "not send it again."
        ),
        required=False,
    )
    attendance_certificate_mail_subject = I18nFormField(
        label=_("Email subject"),
        widget=I18nTextInput,
    )
    attendance_certificate_mail_text = I18nFormField(
        label=_("Email text"),
        help_text=_(
            "Used for automatic sends and for the button on the order page. "
            "Placeholders such as {event} are replaced."
        ),
        widget=I18nTextarea,
    )


class AttendanceCertificateSettingsView(EventSettingsViewMixin, EventSettingsFormView):
    model = Event
    form_class = AttendanceCertificateSettingsForm
    template_name = "pretix_attendance_certificate/settings.html"
    permission = "can_change_event_settings"

    def get_success_url(self) -> str:
        return reverse(
            "plugins:pretix_attendance_certificate:settings",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )
