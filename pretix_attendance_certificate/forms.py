from django import forms

from pretix_attendance_certificate.models import AttendanceCertificateLayout


class OrganizerLayoutForm(forms.ModelForm):
    class Meta:
        model = AttendanceCertificateLayout
        fields = ["name"]
