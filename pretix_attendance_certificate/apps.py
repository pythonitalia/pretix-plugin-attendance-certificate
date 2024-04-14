from django.utils.translation import gettext_lazy
from importlib.metadata import version
from django.utils.translation import gettext

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    name = "pretix_attendance_certificate"
    verbose_name = "Attendance Certificate"

    class PretixPluginMeta:
        name = gettext_lazy("Attendance Certificate")
        author = "Python Italia"
        description = gettext_lazy("Create Attendance Certificates for your attendees")
        visible = True
        version = version("pretix-plugin-attendance-certificate")
        category = "FEATURE"
        compatibility = "pretix>=2.7.0"

    def ready(self):
        from . import signals  # NOQA

    def installed(self, event):
        if not event.attendance_certificate_layouts.exists():
            event.attendance_certificate_layouts.create(
                name=gettext("Default"),
            )


default_app_config = "pretix_attendance_certificate.PluginApp"
