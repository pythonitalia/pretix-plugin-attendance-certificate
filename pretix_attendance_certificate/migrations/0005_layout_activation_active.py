from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pretix_attendance_certificate", "0004_layout_activations"),
    ]

    operations = [
        migrations.AddField(
            model_name="layoutactivation",
            name="active",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="layoutactivation",
            name="checkin_list",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="pretixbase.checkinlist",
            ),
        ),
    ]
