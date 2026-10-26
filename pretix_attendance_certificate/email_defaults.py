from django.utils.translation import gettext_noop
from i18nfield.strings import LazyI18nString

from pretix.base.settings import settings_hierarkey

DEFAULT_SUBJECT = gettext_noop("[{event}] Your certificate of attendance")

DEFAULT_MESSAGE = gettext_noop(
    "Hello,\n\n"
    "please find your certificate of attendance for {event} attached to this "
    "email.\n\n"
    "Best regards"
)

settings_hierarkey.add_default("attendance_certificate_auto_send", False, bool)
settings_hierarkey.add_default(
    "attendance_certificate_mail_subject",
    LazyI18nString.from_gettext(DEFAULT_SUBJECT),
    LazyI18nString,
)
settings_hierarkey.add_default(
    "attendance_certificate_mail_text",
    LazyI18nString.from_gettext(DEFAULT_MESSAGE),
    LazyI18nString,
)


def _serializable(value: LazyI18nString):
    # Defaults hold lazy gettext proxies, which Celery cannot serialize.
    if isinstance(value.data, dict):
        return {lng: str(text) for lng, text in value.data.items()}
    return str(value.data)


def mail_texts(event) -> dict:
    """Subject and message configured for this event, as task kwargs."""
    return {
        "subject": _serializable(event.settings.attendance_certificate_mail_subject),
        "message": _serializable(event.settings.attendance_certificate_mail_text),
    }
