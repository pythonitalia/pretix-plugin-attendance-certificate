from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pretix_attendance_certificate", "0006_organizer_signing_certificate"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizersigningcertificate",
            name="chain_pem",
            field=models.TextField(blank=True, default=""),
        ),
    ]
