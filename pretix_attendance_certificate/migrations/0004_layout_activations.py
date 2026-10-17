from django.db import migrations, models
import django.db.models.deletion


def copy_activations_forward(apps, schema_editor):
    Layout = apps.get_model("pretix_attendance_certificate", "AttendanceCertificateLayout")
    Activation = apps.get_model("pretix_attendance_certificate", "LayoutActivation")
    Old = Layout.active_events.through
    Activation.objects.bulk_create(
        [
            Activation(layout_id=row.attendancecertificatelayout_id, event_id=row.event_id)
            for row in Old.objects.all()
        ]
    )


def copy_activations_backward(apps, schema_editor):
    Layout = apps.get_model("pretix_attendance_certificate", "AttendanceCertificateLayout")
    Activation = apps.get_model("pretix_attendance_certificate", "LayoutActivation")
    Old = Layout.active_events.through
    Old.objects.bulk_create(
        [
            Old(attendancecertificatelayout_id=a.layout_id, event_id=a.event_id)
            for a in Activation.objects.filter(layout__organizer__isnull=False)
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("pretixbase", "0235_auto_20230316_2023"),
        ("pretix_attendance_certificate", "0003_per_layout_mail_text"),
    ]

    operations = [
        migrations.CreateModel(
            name="LayoutActivation",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "checkin_list",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="pretixbase.checkinlist",
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_certificate_activations",
                        to="pretixbase.event",
                    ),
                ),
                (
                    "layout",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activations",
                        to="pretix_attendance_certificate.attendancecertificatelayout",
                    ),
                ),
            ],
            options={"unique_together": {("layout", "event")}},
        ),
        migrations.RunPython(copy_activations_forward, copy_activations_backward),
        migrations.RemoveField(
            model_name="attendancecertificatelayout",
            name="active_events",
        ),
        migrations.AddField(
            model_name="attendancecertificatelayout",
            name="active_events",
            field=models.ManyToManyField(
                blank=True,
                related_name="active_organizer_certificate_layouts",
                through="pretix_attendance_certificate.LayoutActivation",
                through_fields=("layout", "event"),
                to="pretixbase.Event",
            ),
        ),
    ]
