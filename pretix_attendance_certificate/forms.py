from django import forms
from django.utils.translation import gettext_lazy as _

from pretix.plugins.sendmail.forms import FormPlaceholderMixin

from pretix_attendance_certificate.models import AttendanceCertificateLayout

# Organizer-wide templates have no single event to ask which placeholders
# exist, so they get a general note instead of the generated list.
ORGANIZER_PLACEHOLDER_HELP = _(
    "Placeholders: {event} (event name), {name} (attendee's full name), "
    "{name_for_salutation} (name as used in a salutation, e.g. \"Mr Doe\"), "
    "{code} (order code), {url} (link to the order page). Heads-up: "
    "{name_given_name} (first name) and {name_family_name} (last name) only exist "
    "for events that collect the name in parts. For any other event they are sent "
    "as literal text, so use {name} if the template is shared between events. "
    "Which further placeholders exist (e.g. event meta data) depends on the event."
)


class OrganizerLayoutForm(FormPlaceholderMixin, forms.ModelForm):
    class Meta:
        model = AttendanceCertificateLayout
        fields = ["name", "mail_subject", "mail_text"]

    def __init__(self, *args, **kwargs):
        locales = kwargs.pop("locales", None)
        # Only set for event templates (see EventLayoutFormMixin).
        self.event = kwargs.pop("event", None)
        super().__init__(*args, **kwargs)
        # I18nCharField/I18nTextField build one sub-field per locale in
        # settings.LANGUAGES by default (dozens) unless told otherwise - a
        # plain ModelForm has no event/organizer to infer that from, so the
        # view passes the right locale list in explicitly.
        if locales:
            for fname in ("mail_subject", "mail_text"):
                field = self.fields[fname]
                self.fields[fname] = field.__class__(
                    locales=locales,
                    widget=field.widget.__class__,
                    label=field.label,
                    required=field.required,
                )
        for fname in ("mail_subject", "mail_text"):
            if self.event is None:
                self.fields[fname].help_text = ORGANIZER_PLACEHOLDER_HELP
            else:
                # Exactly what the "Send out certificates" page does: lists the
                # placeholders pretix offers for this event and rejects unknown
                # ones on save.
                self._set_field_placeholders(
                    fname, ["event", "order", "position_or_address"]
                )
