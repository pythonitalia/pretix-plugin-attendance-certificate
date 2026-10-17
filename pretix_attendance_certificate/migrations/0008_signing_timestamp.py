from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pretix_attendance_certificate", "0007_signing_chain"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizersigningcertificate",
            name="timestamp_mode",
            field=models.CharField(
                choices=[
                    ("off", "Off"),
                    ("optional", "On, if possible (sign without if unreachable)"),
                    ("required", "On, required (fail if unreachable)"),
                ],
                default="off",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="organizersigningcertificate",
            name="timestamp_url",
            field=models.URLField(blank=True, max_length=255),
        ),
    ]
