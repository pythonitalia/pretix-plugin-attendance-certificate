from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pretixbase", "0235_auto_20230316_2023"),
        ("pretix_attendance_certificate", "0005_layout_activation_active"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizerSigningCertificate",
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
                ("certificate_pem", models.TextField()),
                ("private_key_pem", models.TextField()),
                ("enabled", models.BooleanField(default=True)),
                (
                    "reason",
                    models.CharField(
                        blank=True, default="Certificate of attendance", max_length=190
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                (
                    "organizer",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_certificate_signing",
                        to="pretixbase.organizer",
                    ),
                ),
            ],
        ),
    ]
