from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext, gettext_lazy as _
from django.views.generic import TemplateView, View

from pretix.control.permissions import OrganizerPermissionRequiredMixin
from pretix.control.views.organizer import OrganizerDetailViewMixin

from pretix_attendance_certificate.forms import (
    GenerateCertificateForm,
    ImportCertificateForm,
    SigningSettingsForm,
)
from pretix_attendance_certificate.models import OrganizerSigningCertificate
from pretix_attendance_certificate.signing import (
    certificate_info,
    chain_info,
    check_pair,
    generate_self_signed,
)

LOG_ACTION = "pretix.plugins.pretix_attendance_certificate.signing.changed"


class SigningMixin(OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin):
    permission = "can_change_organizer_settings"

    def get_current(self):
        return OrganizerSigningCertificate.objects.filter(
            organizer=self.request.organizer
        ).first()

    def success_url(self):
        return reverse(
            "plugins:pretix_attendance_certificate:organizer.signing",
            kwargs={"organizer": self.request.organizer.slug},
        )


class SigningView(SigningMixin, TemplateView):
    template_name = "pretix_attendance_certificate/organizer_signing.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        current = self.get_current()
        ctx["current"] = current
        ctx["info"] = certificate_info(current.certificate_pem) if current else None
        ctx["chain"] = chain_info(current.chain_pem) if current else []
        ctx["settings_form"] = kwargs.get("settings_form") or (
            SigningSettingsForm(instance=current) if current else None
        )
        ctx["generate_form"] = kwargs.get("generate_form") or GenerateCertificateForm(
            prefix="generate", initial={"common_name": self.request.organizer.name}
        )
        ctx["import_form"] = kwargs.get("import_form") or ImportCertificateForm(
            prefix="import"
        )
        return ctx

    def _store(self, certificate_pem, private_key_pem, chain_pem=""):
        check_pair(certificate_pem, private_key_pem)
        obj = self.get_current() or OrganizerSigningCertificate(
            organizer=self.request.organizer,
            # Shown by PDF readers; only preset for new certificates so that a
            # reason the organizer has edited survives replacing the certificate.
            reason=gettext("Certificate of attendance"),
        )
        obj.certificate_pem = certificate_pem
        obj.private_key_pem = private_key_pem
        obj.chain_pem = chain_pem
        obj.enabled = True
        obj.save()
        self.request.organizer.log_action(
            LOG_ACTION,
            user=self.request.user,
            data={
                "action": "replaced",
                "fingerprint": certificate_info(certificate_pem).fingerprint,
            },
        )
        return obj

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        current = self.get_current()

        if action == "settings" and current:
            form = SigningSettingsForm(request.POST, instance=current)
            if form.is_valid():
                form.save()
                request.organizer.log_action(
                    LOG_ACTION,
                    user=request.user,
                    data={k: str(form.cleaned_data[k]) for k in form.changed_data},
                )
                messages.success(request, _("Your changes have been saved."))
                return redirect(self.success_url())
            return self.render_to_response(
                self.get_context_data(settings_form=form)
            )

        if action == "generate":
            form = GenerateCertificateForm(request.POST, prefix="generate")
            if form.is_valid():
                cert, key = generate_self_signed(
                    form.cleaned_data["common_name"],
                    form.cleaned_data["organization"],
                    valid_days=form.cleaned_data["valid_years"] * 365,
                )
                self._store(cert, key)
                messages.success(
                    request, _("A new self-signed certificate has been created.")
                )
                return redirect(self.success_url())
            return self.render_to_response(self.get_context_data(generate_form=form))

        if action == "import":
            form = ImportCertificateForm(request.POST, request.FILES, prefix="import")
            if form.is_valid():
                self._store(*form.cleaned_data["pems"])
                messages.success(request, _("The certificate has been imported."))
                return redirect(self.success_url())
            return self.render_to_response(self.get_context_data(import_form=form))

        if action == "delete" and current:
            request.organizer.log_action(
                LOG_ACTION,
                user=request.user,
                data={
                    "action": "deleted",
                    "fingerprint": certificate_info(
                        current.certificate_pem
                    ).fingerprint,
                },
            )
            current.delete()
            messages.success(
                request,
                _(
                    "The certificate has been removed. Certificates of attendance "
                    "are no longer signed."
                ),
            )
            return redirect(self.success_url())

        messages.error(request, _("Your changes could not be saved."))
        return redirect(self.success_url())


class SigningCertificateDownloadView(SigningMixin, View):
    """The *public* certificate, to be published on the organization's website
    so recipients can verify signatures. The private key is never served."""

    def get(self, request, *args, **kwargs):
        current = self.get_current()
        if current is None:
            return redirect(self.success_url())
        response = HttpResponse(
            current.certificate_pem, content_type="application/x-pem-file"
        )
        response["Content-Disposition"] = 'attachment; filename="{}.pem"'.format(
            request.organizer.slug
        )
        return response
