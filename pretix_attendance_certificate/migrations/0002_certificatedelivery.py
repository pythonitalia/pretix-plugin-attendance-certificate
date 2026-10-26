from django.db import migrations, models
import django.db.models.deletion
from django.utils.translation import gettext_lazy as _


class Migration(migrations.Migration):
    dependencies = [
        ("pretix_attendance_certificate", "0001_initial"),
        ("pretixbase", "0235_auto_20230316_2023"),
    ]

    operations = [
        migrations.CreateModel(
            name="CertificateDelivery",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("sending", _("Sending")),
                            ("sent", _("Sent")),
                            ("failed", _("Failed")),
                        ],
                        default="sending",
                        max_length=20,
                    ),
                ),
                ("recipient", models.EmailField(blank=True, max_length=254)),
                ("automatic", models.BooleanField(default=False)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated", models.DateTimeField(auto_now=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True)),
                (
                    "position",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_certificate_delivery",
                        to="pretixbase.orderposition",
                    ),
                ),
            ],
            options={
                "ordering": ("-updated",),
            },
        ),
    ]
